import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SYNC_SCRIPT = Path("/Users/Totoro/Desktop/convert-x-likes-to-markdown/scripts/sync_x_likes.py")


class SyncXLikesICloudPublishModeTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("sync_xlikes_icloud_test_module", SYNC_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _write_stage(self, stage_root: Path) -> None:
        (stage_root / "01 Date" / "2026" / "1 月").mkdir(parents=True, exist_ok=True)
        (stage_root / "02 Author").mkdir(parents=True, exist_ok=True)
        (stage_root / "03 Domain" / "AI").mkdir(parents=True, exist_ok=True)
        (stage_root / "01 Date" / "2026" / "1 月" / "Index.md").write_text("# date\n", encoding="utf-8")
        (stage_root / "02 Author" / "Index.md").write_text("# author\n", encoding="utf-8")
        (stage_root / "03 Domain" / "AI" / "Index.md").write_text("# domain\n", encoding="utf-8")
        (stage_root / "03 Domain" / "Index.md").write_text("# domain root\n", encoding="utf-8")
        (stage_root / "Dashboard.md").write_text("# dash\n", encoding="utf-8")

    def test_is_icloud_target_root_matches_mobile_documents_prefix(self):
        sync = self._load_module()
        icloud_target = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Vault"
        self.assertTrue(sync.is_icloud_target_root(icloud_target))

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(sync.is_icloud_target_root(Path(tmp)))

    def test_local_build_root_for_target_uses_codex_state_hash(self):
        sync = self._load_module()
        icloud_target = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Vault"

        with tempfile.TemporaryDirectory() as codex_home:
            with patch.dict(os.environ, {"CODEX_HOME": codex_home}, clear=False):
                actual = sync.local_build_root_for_target(icloud_target, "X Likes")

            expected_hash = hashlib.sha1(str(icloud_target.expanduser().resolve()).encode("utf-8")).hexdigest()[:16]
            expected = Path(codex_home).resolve() / "state" / "convert-x-likes-to-markdown" / expected_hash / "X Likes"
            self.assertEqual(actual, expected)

    def test_local_build_root_for_target_is_none_for_non_icloud_targets(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(sync.local_build_root_for_target(Path(tmp), "X Likes"))

    def test_icloud_publish_cycle_preserves_search_and_removes_empty_duplicate_dirs(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as fake_home:
            fake_home_path = Path(fake_home)
            target_root = fake_home_path / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Vault" / "Resources"
            output_root = target_root / "X Likes"
            codex_home = fake_home_path / ".codex"

            with patch.dict(
                os.environ,
                {"HOME": str(fake_home_path), "CODEX_HOME": str(codex_home)},
                clear=False,
            ):
                first_stage = sync.local_build_root_for_target(target_root, "X Likes")
                self.assertIsNotNone(first_stage)
                if first_stage.exists():
                    shutil.rmtree(first_stage)
                first_stage.mkdir(parents=True, exist_ok=True)
                self._write_stage(first_stage)

                search_dir = output_root / "04 Search"
                rubbish_dir = output_root / "05 Rubbish"
                search_dir.mkdir(parents=True, exist_ok=True)
                rubbish_dir.mkdir(parents=True, exist_ok=True)
                (search_dir / "query-result.md").write_text("keep me\n", encoding="utf-8")
                (rubbish_dir / "trash.md").write_text("keep me\n", encoding="utf-8")

                sync.replace_target(output_root, first_stage)
                self.assertTrue((search_dir / "query-result.md").exists())
                self.assertTrue((rubbish_dir / "trash.md").exists())

                (output_root / "01 Date" / "2026 2").mkdir(parents=True, exist_ok=True)
                (output_root / "03 Domain" / "AI 2").mkdir(parents=True, exist_ok=True)

                second_stage = sync.local_build_root_for_target(target_root, "X Likes")
                if second_stage.exists():
                    shutil.rmtree(second_stage)
                second_stage.mkdir(parents=True, exist_ok=True)
                self._write_stage(second_stage)

                sync.replace_target(output_root, second_stage)
                sync.normalize_date_tree(output_root / "01 Date")
                sync.cleanup_empty_duplicate_dirs(output_root / "01 Date")
                sync.cleanup_empty_duplicate_dirs(output_root / "03 Domain")

                self.assertFalse((output_root / "01 Date" / "2026 2").exists())
                self.assertFalse((output_root / "03 Domain" / "AI 2").exists())
                self.assertTrue((search_dir / "query-result.md").exists())
                self.assertTrue((rubbish_dir / "trash.md").exists())


if __name__ == "__main__":
    unittest.main()
