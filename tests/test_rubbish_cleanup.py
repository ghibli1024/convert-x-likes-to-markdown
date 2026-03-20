import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SYNC_SCRIPT = Path("/Users/Totoro/Desktop/convert-x-likes-to-markdown/scripts/sync_x_likes.py")


class SyncXLikesRubbishCleanupTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("sync_xlikes_rubbish_test_module", SYNC_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _write_note(self, path: Path, tweet_id: str, source: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(
                f"""\
                ---
                tweet_id: "{tweet_id}"
                title: "{path.stem}"
                author_handle: "alice"
                author_name: "Alice"
                created_at: "2026-03-20"
                source: "{source}"
                domain: "人工智能/对话与聚合/工具与资源"
                ---

                # {path.stem}
                """
            ),
            encoding="utf-8",
        )

    def test_collect_rubbish_tweet_ids_from_note_links_and_urls(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "X Likes"
            note = root / "01 Date" / "2026" / "3 月" / "Hello.md"
            self._write_note(note, "123", "https://x.com/alice/status/123")

            rubbish = root / "05 Rubbish" / "to-delete.md"
            rubbish.parent.mkdir(parents=True, exist_ok=True)
            rubbish.write_text(
                "\n".join(
                    [
                        "# 待删",
                        "- [[01 Date/2026/3 月/Hello|Hello]]",
                        "- https://x.com/bob/status/456",
                    ]
                ),
                encoding="utf-8",
            )

            ids = sync.collect_rubbish_tweet_ids(root)

            self.assertEqual(ids, {"123", "456"})

    def test_apply_rubbish_filter_removes_matching_records(self):
        sync = self._load_module()
        rec1 = sync.Record(
            tweet_id="123",
            title="A",
            author_handle="alice",
            author_name="Alice",
            created_at="2026-03-20",
            source="https://x.com/alice/status/123",
            domain_parts=["人工智能", "对话与聚合", "工具与资源"],
            domain_tag="domain/x",
            topic_tags=[],
            favorite_count=0,
            retweet_count=0,
            reply_count=0,
            quote_count=0,
            bookmark_count=0,
            views_count=0,
            content="A",
            media_lines=[],
        )
        rec2 = sync.Record(
            tweet_id="456",
            title="B",
            author_handle="bob",
            author_name="Bob",
            created_at="2026-03-20",
            source="https://x.com/bob/status/456",
            domain_parts=["人工智能", "对话与聚合", "工具与资源"],
            domain_tag="domain/x",
            topic_tags=[],
            favorite_count=0,
            retweet_count=0,
            reply_count=0,
            quote_count=0,
            bookmark_count=0,
            views_count=0,
            content="B",
            media_lines=[],
        )

        merged = {"123": rec1, "456": rec2}
        sync.apply_rubbish_filter(merged, {"123"})

        self.assertEqual(set(merged.keys()), {"456"})

    def test_clear_rubbish_folder_keeps_folder_but_removes_contents(self):
        sync = self._load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "X Likes"
            rubbish = root / "05 Rubbish"
            nested = rubbish / "nested"
            nested.mkdir(parents=True, exist_ok=True)
            (rubbish / "a.md").write_text("x\n", encoding="utf-8")
            (nested / "b.md").write_text("y\n", encoding="utf-8")

            sync.clear_rubbish_folder(root)

            self.assertTrue(rubbish.exists())
            self.assertEqual(list(rubbish.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
