import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SYNC_SCRIPT = Path("/Users/Totoro/Desktop/convert-x-likes-to-markdown/scripts/sync_x_likes.py")


class SyncXLikesDateNormalizationTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("sync_xlikes_date_normalize_test_module", SYNC_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_normalize_date_tree_merges_duplicate_year_and_english_month(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            date_root = Path(tmp) / "01 Date"
            (date_root / "2025" / "3 月").mkdir(parents=True)
            (date_root / "2025 2" / "Mar").mkdir(parents=True)
            (date_root / "2025" / "3 月" / "Index.md").write_text("# a\n", encoding="utf-8")
            (date_root / "2025 2" / "Mar" / "Index.md").write_text("# a\n", encoding="utf-8")

            sync.normalize_date_tree(date_root)

            self.assertTrue((date_root / "2025").exists())
            self.assertFalse((date_root / "2025 2").exists())
            self.assertTrue((date_root / "2025" / "3 月").exists())
            self.assertFalse((date_root / "2025" / "Mar").exists())


if __name__ == "__main__":
    unittest.main()
