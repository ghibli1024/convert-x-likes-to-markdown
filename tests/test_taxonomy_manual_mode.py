import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SYNC_PATH = Path("/Users/Totoro/.codex/skills/x-to-obsidian/scripts/sync_x_likes.py")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TaxonomyManualModeTest(unittest.TestCase):
    def setUp(self):
        self.sync = load_module(SYNC_PATH, "sync_x_likes_taxonomy_test")
        self.temp_dir = Path(tempfile.mkdtemp(prefix="xlikes-taxonomy-test-"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def write_taxonomy(self, path: Path) -> None:
        path.write_text(
            """# ROOT分类目录

FORMAT: AI_OUTLINE_V1
ROOT_LABEL: ROOT
TOTAL_CANONICAL_PATHS: 8
CONTAINS_URLS: false
PRIMARY_GOAL: taxonomy test

## 一级主类速览

### 工具

- 人工智能：聊天画图等大模型
- 在线工具：在线工具

### 信息

- 学习充电：学习与课程

## 一级分组索引

2.1 工具 | category_count=2 | path_count=4 | node_count=4 | scope=软件工具与 AI
2.2 信息 | category_count=1 | path_count=2 | node_count=2 | scope=信息学习

## 机器大纲

3.0 ROOT | type=root | note=唯一根节点

### 工具

3.1 工具 | type=macro_group | child_count=2 | scope=软件工具与 AI
3.1.1 人工智能 | type=primary_category | alias=- | child_count=1 | scope=聊天画图等大模型
3.1.1.1 AI图像生成 | type=category | child_count=0 | scope=文生图 绘图 图像生成
3.1.2 在线工具 | type=primary_category | alias=- | child_count=1 | scope=在线转换与效率工具
3.1.2.1 文本相关 | type=category | child_count=0 | scope=文本 OCR 文档处理

### 信息

3.2 信息 | type=macro_group | child_count=1 | scope=信息学习
3.2.1 学习充电 | type=primary_category | alias=- | child_count=1 | scope=学习与课程
3.2.1.1 AI学习指南 | type=category | child_count=0 | scope=教程 学习 指南 课程

## 4. 规范路径清单

4.1 PATH = ROOT / 工具
4.2 PATH = ROOT / 工具 / 人工智能
4.3 PATH = ROOT / 工具 / 人工智能 / AI图像生成
4.4 PATH = ROOT / 工具 / 在线工具
4.5 PATH = ROOT / 工具 / 在线工具 / 文本相关
4.6 PATH = ROOT / 信息
4.7 PATH = ROOT / 信息 / 学习充电
4.8 PATH = ROOT / 信息 / 学习充电 / AI学习指南
""",
            encoding="utf-8",
        )

    def test_resolve_manual_rules_path_prefers_explicit_then_archive_then_default(self):
        output_root = self.temp_dir / "X Likes"
        output_root.mkdir(parents=True, exist_ok=True)
        explicit = self.temp_dir / "explicit.md"
        archive_root = output_root / "03 Domain" / "ROOT分类目录.md"
        archive_root.parent.mkdir(parents=True, exist_ok=True)
        default_root = self.temp_dir / "default.md"
        for path in (explicit, archive_root, default_root):
            path.write_text("# x\n", encoding="utf-8")

        with mock.patch.object(self.sync, "DEFAULT_ROOT_TAXONOMY_PATH", default_root):
            chosen = self.sync.resolve_manual_rules_path(output_root, str(explicit))
            self.assertEqual(chosen, explicit.resolve())

            chosen = self.sync.resolve_manual_rules_path(output_root, None)
            self.assertEqual(chosen, archive_root.resolve())

            archive_root.unlink()
            chosen = self.sync.resolve_manual_rules_path(output_root, None)
            self.assertEqual(chosen, default_root.resolve())

    def test_load_manual_rules_accepts_ai_outline_markdown(self):
        taxonomy = self.temp_dir / "ROOT分类目录.md"
        self.write_taxonomy(taxonomy)

        rules = self.sync.load_manual_rules(taxonomy)
        self.assertEqual(rules["rule_source_format"], "taxonomy_ai_outline")
        self.assertIn("工具", rules["top_domains"])
        self.assertIn("信息", rules["top_domains"])
        self.assertTrue(callable(rules["taxonomy_classifier"]))

    def test_manual_taxonomy_classifies_record_into_taxonomy_path(self):
        taxonomy = self.temp_dir / "ROOT分类目录.md"
        self.write_taxonomy(taxonomy)
        rules = self.sync.load_manual_rules(taxonomy)

        parts, tag, topics = self.sync.manual_classify(
            title="ComfyUI prompt guide",
            content="This tutorial explains image generation workflow and prompt design.",
            source="https://example.com/ai/comfyui-guide",
            rules=rules,
            media_lines=[],
            existing_domain_parts=["AI", "图像与视频"],
        )

        self.assertEqual(parts, ["工具", "人工智能", "AI图像生成"])
        self.assertTrue(tag.startswith("domain/"))
        self.assertEqual(topics, [])

    def test_detect_archive_language_prefers_existing_chinese_dashboard(self):
        output_root = self.temp_dir / "X Likes"
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "Dashboard.md").write_text("# X 喜欢仪表盘\n\n## 月份统计\n", encoding="utf-8")

        self.assertEqual(self.sync.detect_archive_language(output_root), "zh")

    def test_render_structure_uses_parent_index_instead_of_duplicate_top_level_leaf(self):
        self.sync.set_active_language("zh")
        self.sync.register_manual_top_domains({"top_domains": ["工具"]})
        stage_root = self.temp_dir / "stage"
        stage_root.mkdir(parents=True, exist_ok=True)

        records = {
            "1": self.sync.Record(
                tweet_id="1",
                title="工具总览",
                author_handle="a",
                author_name="A",
                created_at="2026-04-01",
                source="https://example.com/tool-root",
                domain_parts=["工具"],
                domain_tag="domain/tool",
                topic_tags=[],
                favorite_count=0,
                retweet_count=0,
                reply_count=0,
                quote_count=0,
                bookmark_count=0,
                views_count=0,
                content="工具类总览",
                media_lines=[],
            ),
            "2": self.sync.Record(
                tweet_id="2",
                title="AI 作图",
                author_handle="b",
                author_name="B",
                created_at="2026-04-02",
                source="https://example.com/ai-image",
                domain_parts=["工具", "人工智能", "AI图像生成"],
                domain_tag="domain/ai-image",
                topic_tags=[],
                favorite_count=0,
                retweet_count=0,
                reply_count=0,
                quote_count=0,
                bookmark_count=0,
                views_count=0,
                content="图像生成工作流",
                media_lines=[],
            ),
        }

        self.sync.render_structure(stage_root, records)

        self.assertFalse((stage_root / "03 Domain" / "工具.md").exists())
        self.assertTrue((stage_root / "03 Domain" / "工具" / "Index.md").exists())

    def test_cleanup_duplicate_suffix_files_removes_author_conflict_copies(self):
        author_root = self.temp_dir / "02 Author"
        author_root.mkdir(parents=True, exist_ok=True)
        canonical = author_root / "alice.md"
        duplicate = author_root / "alice 2.md"
        canonical.write_text("same\n", encoding="utf-8")
        duplicate.write_text("same\n", encoding="utf-8")

        self.sync.normalize_author_tree(author_root)

        self.assertTrue(canonical.exists())
        self.assertFalse(duplicate.exists())

    def test_ensure_local_root_taxonomy_copies_into_domain_root(self):
        output_root = self.temp_dir / "X Likes"
        (output_root / "03 Domain").mkdir(parents=True, exist_ok=True)
        source = self.temp_dir / "source-taxonomy.md"
        source.write_text("# ROOT分类目录\n", encoding="utf-8")

        self.sync.ensure_local_root_taxonomy(
            output_root,
            source,
            {"rule_source_format": "taxonomy_ai_outline"},
        )

        self.assertTrue((output_root / "03 Domain" / "ROOT分类目录.md").exists())
        self.assertFalse((output_root / "ROOT分类目录.md").exists())


if __name__ == "__main__":
    unittest.main()
