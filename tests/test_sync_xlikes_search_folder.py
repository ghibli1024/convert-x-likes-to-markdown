import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SYNC_SCRIPT = Path("/Users/Totoro/Desktop/convert-x-likes-to-markdown/scripts/sync_x_likes.py")


class SyncXLikesSearchFolderTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("sync_xlikes_search_test_module", SYNC_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_replace_target_preserves_existing_search_folder(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "X Likes"
            stage = Path(tmp) / "stage"
            for folder in ["01 Date", "02 Author", "03 Domain"]:
                (stage / folder).mkdir(parents=True)
                (stage / folder / "Index.md").write_text("# index\n", encoding="utf-8")
            (stage / "Dashboard.md").write_text("# dash\n", encoding="utf-8")

            search_dir = root / "04 Search"
            search_dir.mkdir(parents=True)
            (search_dir / "query-result.md").write_text("keep me\n", encoding="utf-8")

            sync.replace_target(root, stage)

            self.assertTrue((root / "04 Search").exists())
            self.assertTrue((root / "04 Search" / "query-result.md").exists())

    def test_replace_target_creates_search_folder_when_missing(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "X Likes"
            root.mkdir(parents=True)
            stage = Path(tmp) / "stage"
            for folder in ["01 Date", "02 Author", "03 Domain"]:
                (stage / folder).mkdir(parents=True)
                (stage / folder / "Index.md").write_text("# index\n", encoding="utf-8")
            (stage / "Dashboard.md").write_text("# dash\n", encoding="utf-8")

            sync.replace_target(root, stage)

            self.assertTrue((root / "04 Search").exists())


if __name__ == "__main__":
    unittest.main()
