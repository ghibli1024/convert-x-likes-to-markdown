#!/usr/bin/env python3
"""
Sync X likes JSON exports into a local Markdown archive (Obsidian-friendly).

Output structure under: <target-root>/<container-name>/
- fixed top-level folders/files: 01 Date, 02 Author, 03 Domain, Dashboard.md

Modes:
- merge: upsert JSON into an existing archive and rebuild indexes
- create: rebuild from JSON only

Classification:
- auto: JSON-signal classifier (content + metadata + URLs + media)
- manual: first-match rules from a JSON file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


MAX_DOMAIN_FILE_SIZE = 100
MAX_DOMAIN_DEPTH = 8
MAX_TOP_LEVEL_DOMAINS = 20

LANG_PACKS: Dict[str, Dict[str, str]] = {
    "en": {
        "root_date": "01 Date",
        "root_author": "02 Author",
        "root_domain": "03 Domain",
        "root_search": "04 Search",
        "root_rubbish": "05 Rubbish",
        "dashboard_file": "Dashboard.md",
        "index_file": "Index.md",
        "unknown_month": "Unknown Month",
        "untitled": "Untitled",
        "unknown_author": "unknown",
        "none_media": "- (none)",
        "empty_content": "(empty)",
        "fallback_post_prefix": "Post",
        "field_author": "Author",
        "field_created_at": "Created At",
        "field_source": "Source",
        "field_domain": "Domain",
        "section_content": "Content",
        "section_media": "Media",
        "title_date": "Date",
        "title_author": "Author",
        "title_domain": "Domain",
        "title_dashboard": "X Likes Dashboard",
        "label_total": "Total",
        "label_total_authors": "Total Authors",
        "label_total_domains": "Total Domains",
        "section_years": "Years",
        "section_months": "Months",
        "section_notes": "Notes",
        "section_list": "List",
        "section_subcategories": "Subcategories",
        "section_month_stats": "Month Stats",
        "section_domain_stats": "Domain Stats",
        "section_urls": "URLs",
        "summary_show_all_urls": "Show all {count} URLs",
    },
    "zh": {
        "root_date": "01 Date",
        "root_author": "02 Author",
        "root_domain": "03 Domain",
        "root_search": "04 Search",
        "root_rubbish": "05 Rubbish",
        "dashboard_file": "Dashboard.md",
        "index_file": "Index.md",
        "unknown_month": "未知月",
        "untitled": "无标题",
        "unknown_author": "未知",
        "none_media": "- (无)",
        "empty_content": "(空)",
        "fallback_post_prefix": "帖子",
        "field_author": "作者",
        "field_created_at": "发布时间",
        "field_source": "原帖链接",
        "field_domain": "领域",
        "section_content": "内容",
        "section_media": "媒体",
        "title_date": "日期",
        "title_author": "作者",
        "title_domain": "领域",
        "title_dashboard": "X 喜欢仪表盘",
        "label_total": "总计",
        "label_total_authors": "作者总数",
        "label_total_domains": "领域总数",
        "section_years": "年份",
        "section_months": "月份",
        "section_notes": "帖子",
        "section_list": "列表",
        "section_subcategories": "子分类",
        "section_month_stats": "月份统计",
        "section_domain_stats": "领域统计",
        "section_urls": "链接",
        "summary_show_all_urls": "显示全部 {count} 个链接",
    },
}

MONTH_NAMES_EN = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

ACTIVE_LANG = "en"
I18N = LANG_PACKS[ACTIVE_LANG]


@dataclass
class Record:
    tweet_id: str
    title: str
    author_handle: str
    author_name: str
    created_at: str
    source: str
    domain_parts: List[str]
    domain_tag: str
    topic_tags: List[str]
    favorite_count: int
    retweet_count: int
    reply_count: int
    quote_count: int
    bookmark_count: int
    views_count: int
    content: str
    media_lines: List[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync X likes JSON to local Markdown structure.")
    parser.add_argument("--input-json", required=True, help="Path to exported X likes JSON")
    parser.add_argument("--target-root", required=True, help="Root path XX. Output is XX/X Likes/")
    parser.add_argument("--container-name", default="X Likes", help="Container folder inside target root")
    parser.add_argument("--mode", choices=["merge", "create"], required=True)
    parser.add_argument("--classification", choices=["auto", "manual"], required=True)
    parser.add_argument(
        "--title-language",
        choices=["zh", "en"],
        default="en",
        help="Language for generated folder/file/note titles",
    )
    parser.add_argument(
        "--manual-rules",
        help="Path to manual classification rules JSON (required when --classification manual)",
    )
    return parser.parse_args()


def set_active_language(lang: str) -> None:
    global ACTIVE_LANG, I18N
    if lang not in LANG_PACKS:
        raise ValueError(f"unsupported title language: {lang}")
    ACTIVE_LANG = lang
    I18N = LANG_PACKS[lang]


def t(key: str) -> str:
    return I18N[key]


def root_date_name() -> str:
    return t("root_date")


def root_author_name() -> str:
    return t("root_author")


def root_domain_name() -> str:
    return t("root_domain")


def root_search_name() -> str:
    return t("root_search")


def root_rubbish_name() -> str:
    return t("root_rubbish")


def dashboard_name() -> str:
    return t("dashboard_file")


def index_name() -> str:
    return t("index_file")


def index_stem() -> str:
    return Path(index_name()).stem


def fallback_post_title(tweet_id: str) -> str:
    return f"{t('fallback_post_prefix')} {tweet_id[-6:]}"


def month_number(date_str: str) -> int:
    if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        mm = int(date_str[5:7])
        if 1 <= mm <= 12:
            return mm
    return 0


def month_label_from_number(month_num: int) -> str:
    if 1 <= month_num <= 12:
        if ACTIVE_LANG == "en":
            return MONTH_NAMES_EN[month_num - 1]
        return f"{month_num} 月"
    return t("unknown_month")


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]', ' ', value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def quote_yaml(value: object) -> str:
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{s.strip()}"'


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    out: Dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        out[key] = val
    return out, body


def collect_rubbish_tweet_ids(root_dir: Path) -> set[str]:
    rubbish_root = root_dir / root_rubbish_name()
    if not rubbish_root.exists():
        return set()

    ids: set[str] = set()
    status_pat = re.compile(r'https?://(?:twitter\.com|x\.com)/[^)\s"\']+/status/(\d+)')
    wikilink_pat = re.compile(r"\[\[([^\]|#]+)")
    tweet_id_pat = re.compile(r'^tweet_id:\s*"?(\d+)"?$', re.M)

    for md in rubbish_root.rglob("*.md"):
        text = md.read_text(encoding="utf-8", errors="ignore")
        for m in tweet_id_pat.finditer(text):
            ids.add(m.group(1))
        for m in status_pat.finditer(text):
            ids.add(m.group(1))
        for m in wikilink_pat.finditer(text):
            target = m.group(1).strip()
            if not target.startswith(root_date_name() + "/"):
                continue
            note = root_dir / f"{target}.md"
            if not note.exists():
                continue
            note_text = note.read_text(encoding="utf-8", errors="ignore")
            note_match = tweet_id_pat.search(note_text)
            if note_match:
                ids.add(note_match.group(1))
    return ids


def apply_rubbish_filter(records: Dict[str, Record], rubbish_ids: set[str]) -> None:
    for tweet_id in rubbish_ids:
        records.pop(tweet_id, None)


def clear_rubbish_folder(root_dir: Path) -> None:
    rubbish_root = root_dir / root_rubbish_name()
    rubbish_root.mkdir(parents=True, exist_ok=True)
    for entry in list(rubbish_root.iterdir()):
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def parse_yaml_inline_list(value: str) -> List[str]:
    raw = value.strip()
    if not raw.startswith("[") or not raw.endswith("]"):
        return []
    inner = raw[1:-1].strip()
    if not inner:
        return []
    out: List[str] = []
    for item in inner.split(","):
        s = item.strip().strip('"').strip("'").strip()
        if s:
            out.append(s)
    return out


def section_content(text: str, heading: str) -> str:
    marker = f"\n## {heading}\n"
    start = text.find(marker)
    if start == -1:
        return ""
    pos = start + len(marker)
    nxt = text.find("\n## ", pos)
    if nxt == -1:
        return text[pos:].strip()
    return text[pos:nxt].strip()


def normalize_title(raw_text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    title = lines[0] if lines else fallback
    title = re.sub(r"https?://\S+", "", title)
    title = re.sub(r"^(?:@[^\s]+\s*)+", "", title)
    title = re.sub(r"\[[^\]]*\]\s*$", "", title)
    title = re.sub(r"[\[\]{}]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    title = sanitize_filename(title)
    if not title:
        title = fallback
    if len(title) > 38:
        title = title[:38].rstrip()
    return sanitize_filename(title) or fallback


def has_any(text: str, keywords: Sequence[str]) -> bool:
    return any(k and k in text for k in keywords)


def normalize_host(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return ""
    try:
        p = urlparse(s)
    except ValueError:
        return ""
    host = (p.netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def extract_hosts_from_text(text: str) -> List[str]:
    hosts: List[str] = []
    for m in re.findall(r"https?://[^\s)\]>]+", text or ""):
        h = normalize_host(m)
        if h:
            hosts.append(h)
    return hosts


def as_dict(v: object) -> Dict[str, object]:
    return v if isinstance(v, dict) else {}


def as_list(v: object) -> List[object]:
    return v if isinstance(v, list) else []


def clean_rule_label(value: str) -> str:
    s = str(value or "").strip().strip("`").strip()
    if not s:
        return ""
    s = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"^[>\-\*\+\s]+", "", s)
    s = re.sub(r"^\d+[.)]\s*", "", s)
    s = s.replace("📂", " ")
    s = re.sub(r"[`*_]+", " ", s)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"^[^A-Za-z0-9\u4e00-\u9fff]+", "", s)
    s = re.sub(r"\s+", " ", s).strip(" /")
    return s


def normalize_rule_label_key(value: str) -> str:
    s = clean_rule_label(value).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", s)


def extract_markdown_rule_labels(text: str) -> List[str]:
    labels: List[str] = []

    def add(raw: str) -> None:
        clean = clean_rule_label(raw)
        if not clean:
            return
        if clean in {"ROOT", "根目录", "层级统计", "三级目录快速跳转"}:
            return
        labels.append(clean)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("### "):
            add(stripped[4:])

        for m in re.finditer(r"\[\[[^\]|]+\|([^\]]+)\]\]", stripped):
            add(m.group(1))

        if "ROOT /" in stripped:
            plain = stripped.replace("`", "")
            idx = plain.find("ROOT /")
            if idx != -1:
                path_text = plain[idx:]
                parts = [p.strip() for p in path_text.split("/")]
                for part in parts[1:]:
                    add(part)

        if stripped.startswith("- ") and "[[" not in stripped and "|" not in stripped and len(stripped) <= 80:
            add(stripped[2:])

    # Keep first-seen order while deduplicating.
    seen = set()
    out: List[str] = []
    for label in labels:
        key = normalize_rule_label_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def build_label_index(labels: Sequence[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for label in labels:
        key = normalize_rule_label_key(label)
        if key and key not in out:
            out[key] = label
    return out


def pick_rule_label(label_index: Dict[str, str], *candidates: str, default: str) -> str:
    for candidate in candidates:
        key = normalize_rule_label_key(candidate)
        if key in label_index:
            return label_index[key]
    return clean_rule_label(default) or default


# Logical taxonomy inspired by library-style grouping.
TOP_DOMAIN_ORDER: List[str] = [
    "AI",
    "技术与开发",
    "工具与效率",
    "数码与设备",
    "商业与经济",
    "金融与投资",
    "学习与教育",
    "健康与生活",
    "设计与创意",
    "社会与公共议题",
    "文化与娱乐",
    "其他",
]

DOMAIN_EN_MAP: Dict[str, str] = {
    "AI": "AI",
    "技术与开发": "Technology & Development",
    "工具与效率": "Tools & Productivity",
    "数码与设备": "Devices & Hardware",
    "商业与经济": "Business & Economy",
    "金融与投资": "Finance & Investing",
    "学习与教育": "Learning & Education",
    "健康与生活": "Health & Life",
    "设计与创意": "Design & Creativity",
    "社会与公共议题": "Society & Public Issues",
    "文化与娱乐": "Culture & Entertainment",
    "其他": "Misc",
    "编程助手": "Coding Assistants",
    "Agent与自动化": "Agents & Automation",
    "模型与提示词": "Models & Prompts",
    "产品与应用": "Products & Apps",
    "图像与视频": "Image & Video",
    "资讯与研究": "News & Research",
    "编程与开源": "Programming & Open Source",
    "效率工具": "Productivity Tools",
    "视觉与交互": "Visual & Interaction",
    "课程与方法": "Courses & Methods",
    "英语与语言": "English & Language",
    "设备与系统": "Devices & Systems",
    "内容与商业": "Content & Business",
    "经济与宏观": "Economy & Macro",
    "市场与资产": "Markets & Assets",
    "健康管理": "Health Management",
    "政治与政策": "Politics & Policy",
    "社会观察": "Social Observation",
    "社会观点": "Social Opinions",
    "书籍与阅读": "Books & Reading",
    "娱乐与八卦": "Entertainment & Gossip",
    "职场与管理": "Career & Management",
    "效率应用": "Productivity Apps",
    "其他AI主题": "Other AI Topics",
    "前端与交互": "Frontend & Interaction",
    "后端与系统": "Backend & Systems",
    "DevOps与部署": "DevOps & Deployment",
    "语言与框架": "Languages & Frameworks",
    "开源仓库": "Open Source Repos",
    "工程实践": "Engineering Practices",
    "教程文档": "Guides & Docs",
    "工具链": "Toolchains",
    "笔记与知识管理": "Notes & Knowledge Mgmt",
    "自动化流程": "Automation Workflows",
    "应用工具": "Application Tools",
    "方法与实践": "Methods & Practices",
    "考试与备考": "Exams & Preparation",
    "认知与方法": "Cognition & Methods",
    "其他学习": "Other Learning",
    "影视与内容": "Film, Video & Content",
    "其他文化": "Other Culture",
    "宏观经济": "Macroeconomy",
    "商业增长": "Business Growth",
    "创业与产品": "Startups & Product",
    "其他商业": "Other Business",
    "其他主题": "Other Topics",
    "教程与指南": "Tutorials & Guides",
    "工具与资源": "Tools & Resources",
    "资讯与观点": "News & Opinions",
    "案例与实践": "Cases & Practices",
    "清单与收藏": "Lists & Collections",
    "代码技术": "Code & Tech",
    "学习资料": "Learning Resources",
    "工具应用": "Tools & Apps",
    "链接收藏": "Saved Links",
    "图像媒体": "Image Media",
    "短帖观点": "Short Opinions",
    "中短内容": "Short-Medium Content",
    "中篇内容": "Medium Content",
    "长文资料": "Long-form Resources",
    "娱乐八卦": "Entertainment Gossip",
    "政治政策": "Politics & Policy",
    "经济宏观": "Economy & Macro",
    "健康生活": "Health & Life",
    "技术向内容": "Tech-oriented Content",
    "工具向内容": "Tool-oriented Content",
    "学习向内容": "Learning-oriented Content",
    "书籍向内容": "Book-oriented Content",
    "公共议题内容": "Public Issues Content",
    "链接说明": "Link Notes",
    "图文说明": "Media Notes",
    "极短观点": "Very Short Opinions",
    "短段内容": "Short Segment Content",
    "中文段落": "ZH Paragraphs",
    "英文段落": "EN Paragraphs",
    "AI项目": "AI Projects",
    "前端项目": "Frontend Projects",
    "后端项目": "Backend Projects",
    "数据项目": "Data Projects",
    "运维项目": "Ops Projects",
    "其他仓库": "Other Repos",
    "笔记工具": "Note Tools",
    "自动化工具": "Automation Tools",
    "浏览器工具": "Browser Tools",
    "桌面工具": "Desktop Tools",
    "移动工具": "Mobile Tools",
    "中文工具": "ZH Tools",
    "英文工具": "EN Tools",
    "链接工具": "Link Tools",
    "链接技术": "Link Tech",
    "中文技术": "ZH Tech",
    "英文技术": "EN Tech",
    "中文长文": "ZH Long-form",
    "英文长文": "EN Long-form",
    "中文内容": "ZH Content",
    "英文内容": "EN Content",
    "中段内容": "Medium Segment Content",
    "短文内容": "Short Content",
    "通用工具": "General Tools",
    "主题杂项": "Topic Misc",
}

DOMAIN_COMPONENT_EN_MAP: Dict[str, str] = {
    "综合": "General",
    "技术": "Tech",
    "学习": "Learning",
    "工具": "Tools",
    "金融": "Finance",
    "文化": "Culture",
    "中文": "ZH",
    "英文": "EN",
    "链接": "Link",
    "图文": "Media",
    "极短": "VeryShort",
    "短": "Short",
    "中": "Medium",
    "中长": "MediumLong",
    "长": "Long",
}


def localize_domain_part(part: str) -> str:
    if ACTIVE_LANG != "en":
        return part
    if part in DOMAIN_EN_MAP:
        return DOMAIN_EN_MAP[part]
    if "-" in part:
        chunks = [DOMAIN_COMPONENT_EN_MAP.get(x, DOMAIN_EN_MAP.get(x, x)) for x in part.split("-")]
        return "-".join(chunks)
    return part


def localize_domain_parts(parts: Sequence[str]) -> List[str]:
    clean = normalize_domain_parts(parts)
    return [localize_domain_part(p) for p in clean]

ALLOWED_TOP_DOMAINS = set(TOP_DOMAIN_ORDER)


def register_manual_top_domains(rules: Dict[str, object]) -> None:
    for item in as_list(rules.get("top_domains")):
        clean = sanitize_filename(str(item)).strip()
        if not clean:
            continue
        ALLOWED_TOP_DOMAINS.add(clean)
        if clean not in TOP_DOMAIN_ORDER:
            TOP_DOMAIN_ORDER.append(clean)

DOMAIN_TAG_MAP: Dict[str, str] = {
    "AI": "domain/ai",
    "技术与开发": "domain/technology",
    "工具与效率": "domain/tools-productivity",
    "数码与设备": "domain/devices",
    "商业与经济": "domain/business-economy",
    "金融与投资": "domain/finance-investing",
    "学习与教育": "domain/learning-education",
    "健康与生活": "domain/health-life",
    "设计与创意": "domain/design-creative",
    "社会与公共议题": "domain/public-society",
    "文化与娱乐": "domain/culture-entertainment",
    "其他": "domain/misc",
    "AI/编程助手": "domain/ai-coding-assistant",
    "AI/Agent与自动化": "domain/ai-agent-automation",
    "AI/模型与提示词": "domain/ai-model-prompt",
    "AI/产品与应用": "domain/ai-product-app",
    "AI/图像与视频": "domain/ai-image-video",
    "AI/资讯与研究": "domain/ai-news-research",
    "社会与公共议题/政治与政策": "domain/politics-policy",
    "社会与公共议题/经济与宏观": "domain/economy-macro",
    "文化与娱乐/书籍与阅读": "domain/books-reading",
    "文化与娱乐/娱乐与八卦": "domain/gossip-entertainment",
}

LEGACY_DOMAIN_ALIASES: Dict[str, List[str]] = {
    "AI/Agent自动化": ["AI", "Agent与自动化"],
    "AI/Agent 与自动化": ["AI", "Agent与自动化"],
    "AI/图像视频": ["AI", "图像与视频"],
    "AI/模型提示词": ["AI", "模型与提示词"],
    "AI/产品应用": ["AI", "产品与应用"],
    "学习与英语": ["学习与教育", "英语与语言"],
    "社会观察": ["社会与公共议题", "社会观察"],
    "社会与观点": ["社会与公共议题", "社会观点"],
    "职场与管理": ["商业与经济", "职场与管理"],
    "内容与商业": ["商业与经济", "内容与商业"],
    "投资与金融": ["金融与投资"],
    "编程与开源": ["技术与开发", "编程与开源"],
}

LEGACY_TOP_MAP: Dict[str, List[str]] = {
    "编程与开源": ["技术与开发", "编程与开源"],
    "工具与效率": ["工具与效率"],
    "设计与创意": ["设计与创意"],
    "学习与教育": ["学习与教育"],
    "学习与英语": ["学习与教育", "英语与语言"],
    "数码与设备": ["数码与设备"],
    "内容与商业": ["商业与经济", "内容与商业"],
    "投资与金融": ["金融与投资"],
    "健康与生活": ["健康与生活"],
    "社会观察": ["社会与公共议题", "社会观察"],
    "社会与观点": ["社会与公共议题", "社会观点"],
    "职场与管理": ["商业与经济", "职场与管理"],
}


AUTO_DOMAIN_RULES: List[Dict[str, object]] = [
    {
        "domain": ["AI", "编程助手"],
        "keywords": [
            "claude code",
            "cursor",
            "copilot",
            "aider",
            "openclaw",
            "codex",
            "windsurf",
            "roo code",
            "cline",
            "vibe coding",
            "ai coding",
            "编程助手",
            "代码生成",
            "智能编程",
        ],
        "hosts": ["cursor.com", "github.com"],
    },
    {
        "domain": ["AI", "Agent与自动化"],
        "keywords": [
            "agent",
            "agents",
            "multi-agent",
            "mcp",
            "workflow",
            "automation",
            "pipeline",
            "hook",
            "hooks",
            "n8n",
            "zapier",
            "make.com",
            "trigger",
            "orchestration",
            "自动化",
            "工作流",
            "任务流",
            "skill",
            "skills",
        ],
        "hosts": ["n8n.io", "zapier.com", "make.com"],
    },
    {
        "domain": ["AI", "模型与提示词"],
        "keywords": [
            "prompt",
            "system prompt",
            "token",
            "rag",
            "embedding",
            "context engineering",
            "prompt engineering",
            "提示词",
            "上下文工程",
            "指令工程",
            "向量",
            "检索增强",
            "模型参数",
        ],
        "hosts": ["promptingguide.ai", "huggingface.co"],
    },
    {
        "domain": ["AI", "图像与视频"],
        "keywords": [
            "midjourney",
            "stable diffusion",
            "sdxl",
            "comfyui",
            "flux",
            "runway",
            "sora",
            "pika",
            "可灵",
            "图像生成",
            "文生图",
            "视频生成",
            "文生视频",
            "ai video",
            "ai image",
        ],
        "hosts": ["midjourney.com", "runwayml.com", "civitai.com"],
        "media_types": ["video", "animated_gif"],
    },
    {
        "domain": ["AI", "资讯与研究"],
        "keywords": [
            "benchmark",
            "research",
            "paper",
            "arxiv",
            "release",
            "model card",
            "openai",
            "anthropic",
            "deepmind",
            "llm",
            "大模型",
            "论文",
            "评测",
            "发布",
        ],
        "hosts": ["arxiv.org", "openai.com", "anthropic.com", "huggingface.co"],
    },
    {
        "domain": ["AI", "产品与应用"],
        "keywords": [
            "chatgpt",
            "claude",
            "gemini",
            "notebooklm",
            "perplexity",
            "coze",
            "kimi",
            "豆包",
            "通义",
            "manus",
            "assistant",
            "ai app",
            "ai tool",
            "ai 产品",
            "ai 应用",
        ],
        "hosts": ["chatgpt.com", "gemini.google.com", "notebooklm.google.com", "poe.com"],
    },
    {
        "domain": ["技术与开发", "编程与开源"],
        "keywords": [
            "github",
            "git",
            "pull request",
            "commit",
            "repo",
            "oss",
            "open source",
            "python",
            "javascript",
            "typescript",
            "rust",
            "go",
            "node",
            "api",
            "cli",
            "framework",
            "开源",
            "编程",
            "开发",
            "代码",
            "linux",
        ],
        "hosts": ["github.com", "gitlab.com", "npmjs.com", "pypi.org"],
    },
    {
        "domain": ["工具与效率", "效率工具"],
        "keywords": [
            "obsidian",
            "notion",
            "raycast",
            "alfred",
            "extension",
            "plugin",
            "productivity",
            "笔记",
            "工具",
            "效率",
            "插件",
            "终端",
            "快捷键",
        ],
        "hosts": ["obsidian.md", "raycast.com", "notion.so"],
    },
    {
        "domain": ["设计与创意", "视觉与交互"],
        "keywords": [
            "figma",
            "design",
            "ui",
            "ux",
            "typography",
            "layout",
            "visual",
            "brand",
            "字体",
            "设计",
            "排版",
            "动效",
            "视觉",
        ],
        "hosts": ["figma.com", "dribbble.com", "behance.net"],
    },
    {
        "domain": ["学习与教育", "课程与方法"],
        "keywords": [
            "learning",
            "course",
            "tutorial",
            "guide",
            "lesson",
            "study",
            "学习",
            "教程",
            "课程",
            "资料",
            "复习",
            "考试",
        ],
        "hosts": ["coursera.org", "udemy.com", "khanacademy.org", "youtube.com", "youtu.be"],
    },
    {
        "domain": ["学习与教育", "英语与语言"],
        "keywords": ["ielts", "english", "雅思", "英语", "口语", "词汇", "语法"],
        "hosts": [],
    },
    {
        "domain": ["数码与设备", "设备与系统"],
        "keywords": [
            "iphone",
            "ios",
            "mac",
            "macos",
            "ipad",
            "apple",
            "android",
            "esim",
            "sim",
            "chip",
            "hardware",
            "device",
            "设备",
            "数码",
            "手机",
            "硬件",
        ],
        "hosts": ["apple.com", "macrumors.com", "9to5mac.com"],
    },
    {
        "domain": ["商业与经济", "内容与商业"],
        "keywords": [
            "marketing",
            "growth",
            "business",
            "startup",
            "saas",
            "newsletter",
            "运营",
            "增长",
            "商业",
            "创业",
            "流量",
            "变现",
            "品牌",
            "营销",
        ],
        "hosts": ["substack.com"],
    },
    {
        "domain": ["商业与经济", "经济与宏观"],
        "keywords": [
            "economy",
            "macro",
            "gdp",
            "inflation",
            "失业率",
            "经济",
            "通胀",
            "宏观",
            "加息",
            "降息",
        ],
        "hosts": [],
    },
    {
        "domain": ["金融与投资", "市场与资产"],
        "keywords": [
            "investment",
            "finance",
            "stock",
            "etf",
            "trading",
            "crypto",
            "bitcoin",
            "btc",
            "eth",
            "投资",
            "金融",
            "股票",
            "基金",
            "交易",
            "加密",
        ],
        "hosts": ["coindesk.com", "cointelegraph.com", "binance.com"],
    },
    {
        "domain": ["健康与生活", "健康管理"],
        "keywords": [
            "health",
            "sleep",
            "fitness",
            "mental",
            "diet",
            "exercise",
            "健康",
            "睡眠",
            "心理",
            "饮食",
            "运动",
            "医疗",
        ],
        "hosts": [],
    },
    {
        "domain": ["社会与公共议题", "政治与政策"],
        "keywords": [
            "politics",
            "policy",
            "government",
            "election",
            "政治",
            "政策",
            "政府",
            "选举",
            "公共",
        ],
        "hosts": [],
    },
    {
        "domain": ["社会与公共议题", "社会观察"],
        "keywords": ["society", "culture", "trend", "opinion", "社会", "文化", "趋势", "观点", "观察"],
        "hosts": ["news.ycombinator.com"],
    },
    {
        "domain": ["文化与娱乐", "书籍与阅读"],
        "keywords": ["book", "books", "reading", "kindle", "书", "书籍", "阅读", "书单", "作者"],
        "hosts": ["goodreads.com"],
    },
    {
        "domain": ["文化与娱乐", "娱乐与八卦"],
        "keywords": ["gossip", "celebrity", "entertainment", "八卦", "明星", "绯闻", "吃瓜", "娱乐圈"],
        "hosts": [],
    },
]


HOST_FALLBACKS: List[Tuple[List[str], List[str]]] = [
    (["github.com", "gitlab.com", "npmjs.com", "pypi.org"], ["技术与开发", "编程与开源"]),
    (["huggingface.co", "openai.com", "anthropic.com", "arxiv.org"], ["AI", "资讯与研究"]),
    (["obsidian.md", "notion.so", "raycast.com"], ["工具与效率", "效率工具"]),
    (["figma.com", "dribbble.com"], ["设计与创意", "视觉与交互"]),
    (["youtube.com", "youtu.be", "coursera.org", "udemy.com"], ["学习与教育", "课程与方法"]),
    (["apple.com", "macrumors.com", "9to5mac.com"], ["数码与设备", "设备与系统"]),
    (["coindesk.com", "cointelegraph.com", "binance.com"], ["金融与投资", "市场与资产"]),
]


TOPIC_RULES: List[Tuple[str, List[str], List[str]]] = [
    ("topic/obsidian", ["obsidian"], ["obsidian.md"]),
    ("topic/github", ["github", "git", "开源"], ["github.com", "gitlab.com"]),
    ("topic/agent", ["agent", "mcp", "自动化", "workflow", "hook"], []),
    ("topic/prompt", ["prompt", "提示词", "token", "rag"], []),
    ("topic/apple", ["iphone", "ios", "mac", "apple"], ["apple.com", "macrumors.com"]),
    ("topic/english", ["english", "ielts", "英语", "雅思"], []),
    ("topic/crypto", ["crypto", "bitcoin", "btc", "eth", "加密"], ["coindesk.com"]),
    ("topic/politics", ["politics", "policy", "政治", "政策"], []),
    ("topic/books", ["book", "books", "阅读", "书籍", "书单"], []),
]


def normalize_domain_parts(parts: Sequence[str]) -> List[str]:
    clean = [sanitize_filename(str(p)).strip() for p in parts if sanitize_filename(str(p)).strip()]
    if not clean:
        return ["其他"]

    key = "/".join(clean)
    if key in LEGACY_DOMAIN_ALIASES:
        clean = list(LEGACY_DOMAIN_ALIASES[key])

    if clean[0] in LEGACY_TOP_MAP:
        mapped = LEGACY_TOP_MAP[clean[0]]
        clean = list(mapped) + clean[1:]

    if clean[0] == "AI" and len(clean) >= 2:
        ai_alias = {
            "Agent自动化": "Agent与自动化",
            "Agent 与自动化": "Agent与自动化",
            "图像视频": "图像与视频",
            "模型提示词": "模型与提示词",
            "产品应用": "产品与应用",
        }
        clean[1] = ai_alias.get(clean[1], clean[1])

    if clean[0] not in ALLOWED_TOP_DOMAINS:
        clean = ["其他", clean[0]]

    if len(clean) > MAX_DOMAIN_DEPTH:
        clean = clean[:MAX_DOMAIN_DEPTH]

    return clean


def domain_tag_from_parts(parts: Sequence[str]) -> str:
    clean = normalize_domain_parts(parts)
    key = "/".join(clean)
    if key in DOMAIN_TAG_MAP:
        return DOMAIN_TAG_MAP[key]
    if clean and clean[0] in DOMAIN_TAG_MAP:
        return DOMAIN_TAG_MAP[clean[0]]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"domain/manual-{digest}"


def score_rule(text: str, hosts: Sequence[str], media_types: Sequence[str], rule: Dict[str, object]) -> int:
    score = 0
    keywords = [str(k).lower() for k in as_list(rule.get("keywords")) if str(k).strip()]
    host_rules = [str(h).lower() for h in as_list(rule.get("hosts")) if str(h).strip()]
    media_rules = [str(m).lower() for m in as_list(rule.get("media_types")) if str(m).strip()]

    for kw in keywords:
        if kw in text:
            score += 2 if (" " in kw or len(kw) >= 5) else 1

    host_set = set(hosts)
    for h in host_rules:
        if h in host_set:
            score += 3

    media_set = set(media_types)
    for m in media_rules:
        if m in media_set:
            score += 2

    return score


def collect_json_signals(
    item: Dict[str, object],
    title: str,
    content: str,
    source: str,
) -> Tuple[str, List[str], List[str]]:
    text_parts: List[str] = []
    hosts: List[str] = []
    media_types: List[str] = []

    def add_text(v: object) -> None:
        if isinstance(v, str):
            s = v.strip()
            if s:
                text_parts.append(s)

    def add_url(v: object) -> None:
        if not isinstance(v, str):
            return
        h = normalize_host(v)
        if h:
            hosts.append(h)

    add_text(title)
    add_text(content)
    add_text(source)
    add_text(item.get("name"))
    add_text(item.get("screen_name"))
    add_text(item.get("url"))

    for h in extract_hosts_from_text(content):
        hosts.append(h)

    media = as_list(item.get("media"))
    for m in media:
        md = as_dict(m)
        mt = str(md.get("type") or "").strip().lower()
        if mt:
            media_types.append(mt)
        add_url(md.get("original"))
        add_url(md.get("thumbnail"))
        add_url(md.get("url"))

    meta = as_dict(item.get("metadata"))
    legacy = as_dict(meta.get("legacy"))
    add_text(legacy.get("full_text"))

    entities = as_dict(legacy.get("entities"))
    hashtags = as_list(entities.get("hashtags"))
    if hashtags:
        add_text(" ".join(str(as_dict(h).get("text") or "") for h in hashtags))

    for u in as_list(entities.get("urls")):
        ud = as_dict(u)
        add_text(ud.get("expanded_url"))
        add_url(ud.get("expanded_url"))
        add_url(ud.get("url"))

    for m in as_list(entities.get("media")):
        md = as_dict(m)
        add_url(md.get("expanded_url"))
        add_url(md.get("media_url_https"))
        mt = str(md.get("type") or "").strip().lower()
        if mt:
            media_types.append(mt)

    # Skip author profile text to avoid author-level bias.
    quoted_status = item.get("quoted_status")
    if isinstance(quoted_status, dict):
        qd = as_dict(quoted_status)
        add_text(qd.get("full_text"))
        add_text(qd.get("url"))
        add_url(qd.get("url"))

    text_blob = "\n".join(text_parts).lower()
    host_unique = sorted({h for h in hosts if h})
    media_unique = sorted({m for m in media_types if m})
    return text_blob, host_unique, media_unique


def infer_topics(text: str, hosts: Sequence[str]) -> List[str]:
    out: List[str] = []
    host_set = set(hosts)
    for tag, keywords, host_hints in TOPIC_RULES:
        if has_any(text, [k.lower() for k in keywords]) or any(h in host_set for h in host_hints):
            out.append(tag)
    return sorted(set(out))


def infer_domain_from_hosts(hosts: Sequence[str]) -> List[str]:
    host_set = set(hosts)
    for host_list, domain in HOST_FALLBACKS:
        if any(h in host_set for h in host_list):
            return normalize_domain_parts(domain)
    return ["其他"]


def auto_classify(
    item: Dict[str, object],
    title: str,
    content: str,
    source: str,
) -> Tuple[List[str], str, List[str]]:
    text, hosts, media_types = collect_json_signals(item, title, content, source)

    best_domain: List[str] = ["其他"]
    best_score = 0
    second_score = 0
    for rule in AUTO_DOMAIN_RULES:
        score = score_rule(text, hosts, media_types, rule)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_domain = normalize_domain_parts(rule["domain"])
        elif score > second_score:
            second_score = score

    if best_score == 0:
        best_domain = infer_domain_from_hosts(hosts)

    # AI override only when AI signals are strong enough, to avoid over-classifying.
    if best_domain and best_domain[0] != "AI":
        ai_keywords = [
            "ai",
            "aigc",
            "llm",
            "gpt",
            "claude",
            "gemini",
            "openai",
            "anthropic",
            "deepseek",
            "qwen",
            "大模型",
            "模型",
        ]
        ai_hits = sum(1 for k in ai_keywords if k in text)
        ai_host_hits = sum(1 for h in hosts if h in {"openai.com", "anthropic.com", "huggingface.co", "chatgpt.com"})
        if ai_hits >= 2 or (ai_hits >= 1 and ai_host_hits >= 1 and best_score <= max(2, second_score + 1)):
            best_domain = ["AI", "产品与应用"]

    best_domain = normalize_domain_parts(best_domain)
    topics = infer_topics(text, hosts)
    return best_domain, domain_tag_from_parts(best_domain), topics


def manual_rule(domain_parts: Sequence[str], keywords: Sequence[str], hosts: Sequence[str] = ()) -> Dict[str, object]:
    clean_parts = []
    for part in domain_parts:
        clean = clean_rule_label(part).replace("/", " ").strip()
        if clean:
            clean_parts.append(clean)
    rule = {
        "domain": "/".join(clean_parts),
        "keywords": sorted({str(k).strip() for k in keywords if str(k).strip()}),
    }
    if hosts:
        rule["hosts"] = sorted({normalize_host(str(h)) for h in hosts if normalize_host(str(h))})
    return rule


def build_manual_rules_from_markdown(path: Path) -> Dict[str, object]:
    text = path.read_text(encoding="utf-8")
    labels = extract_markdown_rule_labels(text)
    label_index = build_label_index(labels)

    top_ai = pick_rule_label(label_index, "人工智能", default="人工智能")
    top_office = pick_rule_label(label_index, "办公相关", default="办公相关")
    top_learning = pick_rule_label(label_index, "学习相关", default="学习相关")
    top_industry = pick_rule_label(label_index, "各行各业", default="各行各业")
    top_gallery = pick_rule_label(label_index, "图库素材", default="图库素材")
    top_design = pick_rule_label(label_index, "设计相关", default="设计相关")
    top_life = pick_rule_label(label_index, "懂得生活", default="懂得生活")
    top_books = pick_rule_label(label_index, "书籍相关", default="书籍相关")
    top_news = pick_rule_label(label_index, "新闻资讯", default="新闻资讯")
    top_computer = pick_rule_label(label_index, "电脑常用", default="电脑常用")
    top_software = pick_rule_label(label_index, "软件相关", default="软件相关")
    top_video = pick_rule_label(label_index, "影视相关", default="影视相关")
    top_anime = pick_rule_label(label_index, "动漫漫画", default="动漫漫画")
    top_game = pick_rule_label(label_index, "游戏相关", default="游戏相关")
    top_resources = pick_rule_label(label_index, "资源探索", default="资源探索")

    ai_api = pick_rule_label(label_index, "API 资源", default="API 资源")
    ai_writing = pick_rule_label(label_index, "写作文档", default="写作文档")
    ai_image = pick_rule_label(label_index, "图像生成", default="图像生成")
    ai_chat = pick_rule_label(label_index, "对话与聚合", default="对话与聚合")
    ai_prompt = pick_rule_label(label_index, "提示词工程", default="提示词工程")
    ai_agent = pick_rule_label(label_index, "智能体", default="智能体")
    ai_local = pick_rule_label(label_index, "本地部署", default="本地部署")
    ai_geek = pick_rule_label(label_index, "极客开发", default="极客开发")
    ai_kb = pick_rule_label(label_index, "知识库", default="知识库")
    ai_auto = pick_rule_label(label_index, "自动化", default="自动化")

    office_obsidian = pick_rule_label(label_index, "obsidian", default="obsidian")
    office_notion = pick_rule_label(label_index, "notion", default="notion")
    office_feishu = pick_rule_label(label_index, "飞书", default="飞书")
    office_collab = pick_rule_label(label_index, "团队协作", default="团队协作")
    office_pm = pick_rule_label(label_index, "项目管理", default="项目管理")
    office_km = pick_rule_label(label_index, "知识管理系统", default="知识管理系统")
    office_overseas = pick_rule_label(label_index, "开发者出海", default="开发者出海")

    learning_ai = pick_rule_label(label_index, "ai学习教程", default="ai学习教程")
    learning_english = pick_rule_label(label_index, "英语学习", "英语", default="英语学习")
    learning_growth = pick_rule_label(label_index, "增长课程", default="增长课程")

    industry_finance = pick_rule_label(label_index, "股票财经", default="股票财经")
    industry_creator = pick_rule_label(label_index, "自媒体", default="自媒体")

    gallery_ui = pick_rule_label(label_index, "UI/UX设计", "UI UX设计", default="UI UX设计")
    design_online = pick_rule_label(label_index, "在线设计", default="在线设计")

    life_health = pick_rule_label(label_index, "医学健康", "营养健康", "身体健康", default="医学健康")
    life_mind = pick_rule_label(label_index, "心理相关", default="心理相关")
    life_tips = pick_rule_label(label_index, "生活技巧", default="生活技巧")

    books_reading = pick_rule_label(label_index, "书单推荐", "书籍分享", "书籍信息", default="书单推荐")
    news_media = pick_rule_label(label_index, "全球媒体导航", "新媒体导航", default="全球媒体导航")
    computer_github = pick_rule_label(label_index, "github相关", default="github相关")
    computer_code = pick_rule_label(label_index, "编程相关", "it导航", default="编程相关")
    software_mac = pick_rule_label(label_index, "mac软件推荐", default="mac软件推荐")
    software_win = pick_rule_label(label_index, "win软件推荐", default="win软件推荐")
    software_android = pick_rule_label(label_index, "安卓软件推荐", default="安卓软件推荐")
    video_watch = pick_rule_label(label_index, "一起观影听歌", "影视导航", default="一起观影听歌")
    anime_acg = pick_rule_label(label_index, "综合acg", "二次元导航", default="综合acg")
    game_nav = pick_rule_label(label_index, "游戏导航", "游戏类", default="游戏导航")

    top_domains = [
        top_ai,
        top_office,
        top_learning,
        top_industry,
        top_gallery,
        top_design,
        top_life,
        top_books,
        top_news,
        top_computer,
        top_software,
        top_video,
        top_anime,
        top_game,
        top_resources,
    ]
    seen_top = set()
    top_domains = [x for x in top_domains if x and not (x in seen_top or seen_top.add(x))]

    rules = [
        manual_rule(
            [top_ai, ai_agent],
            [
                "agent",
                "agents",
                "智能体",
                "mcp",
                "manus",
                "orchestration",
                "tool use",
                "agent workflow",
                "server connector",
                "autonomous",
                "多智能体",
            ],
            ["claude.md"],
        ),
        manual_rule(
            [top_ai, ai_prompt],
            [
                "prompt",
                "prompts",
                "system prompt",
                "system prompts",
                "提示词",
                "prompt engineering",
                "jailbreak",
                "越狱",
            ],
        ),
        manual_rule(
            [top_ai, ai_chat],
            [
                "chatgpt",
                "claude",
                "gemini",
                "deepseek",
                "kimi",
                "grok",
                "llm chat",
                "聊天模型",
                "ai 助手",
                "对话模型",
                "大模型平台",
            ],
            ["claude.ai", "openai.com", "chatgpt.com", "gemini.google.com", "aistudio.google.com"],
        ),
        manual_rule(
            [top_ai, ai_api],
            [
                "api",
                "sdk",
                "api key",
                "openrouter",
                "proxy",
                "gateway",
                "中转",
                "接口",
                "token",
                "rate limit",
            ],
            ["openrouter.ai", "platform.openai.com", "api.anthropic.com"],
        ),
        manual_rule(
            [top_ai, ai_local],
            [
                "ollama",
                "vllm",
                "lm studio",
                "self-hosted",
                "self hosted",
                "local model",
                "本地部署",
                "本地模型",
                "推理引擎",
                "webui",
            ],
            ["huggingface.co"],
        ),
        manual_rule(
            [top_ai, ai_kb],
            [
                "rag",
                "notebooklm",
                "知识库",
                "向量数据库",
                "embedding",
                "semantic search",
                "文档问答",
                "检索增强",
                "pdf chat",
            ],
        ),
        manual_rule(
            [top_ai, ai_image],
            [
                "comfyui",
                "midjourney",
                "stable diffusion",
                "dall-e",
                "flux",
                "runway",
                "sora",
                "图像生成",
                "绘图",
                "绘画",
                "视频生成",
                "多模态",
            ],
        ),
        manual_rule(
            [top_ai, ai_auto],
            [
                "n8n",
                "zapier",
                "make.com",
                "workflow",
                "automation",
                "自动化",
                "工作流",
                "cron",
                "bot",
                "机器人",
            ],
        ),
        manual_rule(
            [top_ai, ai_geek],
            [
                "benchmark",
                "leaderboard",
                "evaluation",
                "模型评测",
                "gpu",
                "serverless",
                "部署成本",
                "price analysis",
                "latency",
                "推理加速",
            ],
        ),
        manual_rule(
            [top_ai, ai_writing],
            [
                "writing",
                "copywriting",
                "文案",
                "写作",
                "润色",
                "论文",
                "博客",
                "内容营销",
                "docs",
                "document",
            ],
        ),
        manual_rule([top_office, office_obsidian], ["obsidian", "dataview", "wikilink", "canvas", "vault"], ["obsidian.md"]),
        manual_rule([top_office, office_notion], ["notion", "notion ai"], ["notion.so", "notion.site"]),
        manual_rule([top_office, office_feishu], ["feishu", "lark", "飞书", "多维表格"], ["feishu.cn", "my.feishu.cn"]),
        manual_rule([top_office, office_km], ["knowledge management", "pkm", "second brain", "知识管理", "笔记系统"]),
        manual_rule([top_office, office_collab], ["collaboration", "协作", "team", "async", "workspace", "团队协作"], ["slack.com", "discord.com"]),
        manual_rule([top_office, office_pm], ["project management", "roadmap", "kanban", "jira", "linear", "scrum", "项目管理"]),
        manual_rule([top_office, office_overseas], ["indie hacker", "indie hacking", "saas", "build in public", "出海", "海外增长", "支付", "订阅"]),
        manual_rule([top_learning, learning_ai], ["教程", "guide", "course", "learning path", "机器学习", "深度学习", "whitepaper", "paper", "ai学习"]),
        manual_rule([top_learning, learning_english], ["english", "ielts", "toefl", "英语", "雅思", "词典", "语法", "listening", "speaking"]),
        manual_rule([top_learning, learning_growth], ["growth", "增长", "增长课程", "marketing course", "运营课程", "增长黑客"]),
        manual_rule(
            [top_industry, industry_finance],
            ["stock", "finance", "invest", "investment", "macro", "btc", "bitcoin", "crypto", "eth", "binance", "okx", "股票", "基金", "量化", "财经"],
            ["binance.com", "okx.com", "coindesk.com", "cointelegraph.com"],
        ),
        manual_rule(
            [top_industry, industry_creator],
            ["creator", "content creator", "newsletter", "自媒体", "博主", "流量", "涨粉", "直播", "短视频", "剪辑", "内容分发"],
        ),
        manual_rule([top_gallery, gallery_ui], ["figma", "design system", "component library", "wireframe", "界面", "交互", "原型", "设计灵感"], ["figma.com", "dribbble.com", "behance.net"]),
        manual_rule([top_design, design_online], ["canva", "photoshop", "illustrator", "海报", "封面", "logo", "视觉设计", "品牌设计", "在线设计"]),
        manual_rule([top_life, life_health], ["health", "medical", "medicine", "sleep", "fitness", "运动", "健康", "医疗", "药品", "营养"]),
        manual_rule([top_life, life_mind], ["心理", "mental", "therapy", "anxiety", "depression", "mindfulness", "认知行为"]),
        manual_rule([top_life, life_tips], ["生活技巧", "life tips", "kitchen", "travel tips", "household", "效率生活"]),
        manual_rule([top_books, books_reading], ["book", "books", "reading", "kindle", "书", "阅读", "书单", "电子书", "作者"], ["goodreads.com"]),
        manual_rule([top_news, news_media], ["news", "breaking", "报道", "媒体", "journalism", "记者", "时评", "资讯"]),
        manual_rule([top_computer, computer_github], ["github", "gitlab", "repo", "repository", "star", "readme", "开源仓库"], ["github.com", "gitlab.com"]),
        manual_rule([top_computer, computer_code], ["python", "javascript", "typescript", "rust", "golang", "backend", "frontend", "database", "linux", "编程", "开发", "架构", "代码"]),
        manual_rule([top_software, software_mac], ["mac app", "macos", "raycast", "alfred", "mac 软件", "mac工具"], ["raycast.com"]),
        manual_rule([top_software, software_win], ["windows app", "win软件", "windows 工具", "pc 软件"]),
        manual_rule([top_software, software_android], ["android app", "apk", "安卓", "android 工具"]),
        manual_rule([top_video, video_watch], ["movie", "film", "tv", "纪录片", "影视", "观影", "剧集", "电影"]),
        manual_rule([top_anime, anime_acg], ["anime", "manga", "动漫", "漫画", "acg", "二次元", "ghibli"]),
        manual_rule([top_game, game_nav], ["game", "gaming", "steam", "游戏", "switch", "xbox", "playstation"]),
    ]

    topic_rules = [
        {"tag": "topic/obsidian", "keywords": ["obsidian"], "hosts": ["obsidian.md"]},
        {"tag": "topic/notion", "keywords": ["notion"], "hosts": ["notion.so", "notion.site"]},
        {"tag": "topic/feishu", "keywords": ["feishu", "lark", "飞书"], "hosts": ["feishu.cn", "my.feishu.cn"]},
        {"tag": "topic/github", "keywords": ["github", "gitlab", "开源"], "hosts": ["github.com", "gitlab.com"]},
        {"tag": "topic/agent", "keywords": ["agent", "mcp", "智能体", "manus"]},
        {"tag": "topic/prompt", "keywords": ["prompt", "提示词", "system prompt"]},
        {"tag": "topic/finance", "keywords": ["bitcoin", "btc", "crypto", "股票", "投资"]},
        {"tag": "topic/design", "keywords": ["figma", "ui", "ux", "设计"]},
        {"tag": "topic/english", "keywords": ["english", "英语", "雅思"]},
        {"tag": "topic/health", "keywords": ["health", "健康", "睡眠", "营养"]},
    ]

    return {
        "fallback_domain": f"{top_resources}/其他",
        "top_domains": top_domains,
        "rules": rules,
        "topic_rules": topic_rules,
        "rule_source": str(path),
        "rule_source_format": "markdown",
    }


def load_manual_rules(path: Path) -> Dict[str, object]:
    if path.suffix.lower() == ".md":
        data = build_manual_rules_from_markdown(path)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if "rules" not in data or not isinstance(data["rules"], list):
        raise ValueError("manual rules JSON must include list field: rules")
    fallback = data.get("fallback_domain", "其他")
    if not isinstance(fallback, str) or not fallback.strip():
        raise ValueError("fallback_domain must be non-empty string")
    register_manual_top_domains(data)
    return data


def manual_classify(
    title: str,
    content: str,
    source: str,
    rules: Dict[str, object],
    media_lines: Optional[Sequence[str]] = None,
) -> Tuple[List[str], str, List[str]]:
    media_lines = list(media_lines or [])
    raw_text = f"{title}\n{content}\n{source}\n" + "\n".join(media_lines)
    text = raw_text.lower()
    hosts = sorted(set(extract_hosts_from_text(raw_text)))
    media_types = extract_media_types_from_lines(media_lines)
    rule_list = rules.get("rules", [])
    fallback = str(rules.get("fallback_domain", "其他"))

    chosen_domain = fallback
    chosen_tag = str(rules.get("fallback_tag", "")).strip()

    for rule in rule_list:
        if not isinstance(rule, dict):
            continue
        domain = str(rule.get("domain", "")).strip()
        if not domain:
            continue
        has_keywords = isinstance(rule.get("keywords", []), list) and any(str(k).strip() for k in rule.get("keywords", []))
        has_hosts = isinstance(rule.get("hosts", []), list) and any(str(h).strip() for h in rule.get("hosts", []))
        has_media = isinstance(rule.get("media_types", []), list) and any(str(m).strip() for m in rule.get("media_types", []))
        if not any([has_keywords, has_hosts, has_media]):
            continue
        if score_rule(text, hosts, media_types, rule) > 0:
            chosen_domain = domain
            chosen_tag = str(rule.get("tag", "")).strip()
            break

    parts = normalize_domain_parts([p.strip() for p in chosen_domain.split("/") if p.strip()])

    topics: List[str] = []
    topic_rules = rules.get("topic_rules", [])
    if isinstance(topic_rules, list):
        for tr in topic_rules:
            if not isinstance(tr, dict):
                continue
            tag = str(tr.get("tag", "")).strip()
            if not tag:
                continue
            if score_rule(text, hosts, media_types, tr) > 0:
                topics.append(tag)

    if not chosen_tag.startswith("domain/"):
        chosen_tag = domain_tag_from_parts(parts)

    return parts, chosen_tag, sorted(set(topics))


def parse_media_lines_from_block(media_block: str) -> List[str]:
    lines: List[str] = []
    for line in media_block.splitlines():
        ln = line.strip()
        if ln:
            lines.append(ln)
    return lines


def extract_media_types_from_lines(media_lines: Sequence[str]) -> List[str]:
    out: List[str] = []
    for line in media_lines:
        m = re.match(r"-\s*([A-Za-z0-9_-]+)\b", line.strip())
        if m:
            out.append(m.group(1).lower())
    return out


def domain_rel_link(parts: Sequence[str]) -> str:
    clean = localize_domain_parts(parts)
    if len(clean) == 1:
        return f"{root_domain_name()}/{sanitize_filename(clean[0])}"
    return f"{root_domain_name()}/{'/'.join(sanitize_filename(p) for p in clean[:-1])}/{sanitize_filename(clean[-1])}"


def domain_parent_index_link(parts: Sequence[str]) -> str:
    clean = localize_domain_parts(parts)
    if not clean:
        return f"{root_domain_name()}/{index_stem()}"
    return f"{root_domain_name()}/{'/'.join(sanitize_filename(p) for p in clean)}/{index_stem()}"


def domain_abs_path(domain_root: Path, parts: Sequence[str]) -> Path:
    clean = localize_domain_parts(parts)
    if len(clean) == 1:
        return domain_root / f"{sanitize_filename(clean[0])}.md"
    out_dir = domain_root
    for p in clean[:-1]:
        out_dir = out_dir / sanitize_filename(p)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{sanitize_filename(clean[-1])}.md"


def domain_parent_index_path(domain_root: Path, parts: Sequence[str]) -> Path:
    clean = localize_domain_parts(parts)
    out_dir = domain_root
    for p in clean:
        out_dir = out_dir / sanitize_filename(p)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / index_name()


def parse_existing_records(date_root: Path) -> Dict[str, Record]:
    out: Dict[str, Record] = {}
    if not date_root.exists():
        return out

    for md in date_root.rglob("*.md"):
        if md.name in {cfg["index_file"] for cfg in LANG_PACKS.values()} | {"Index.md", "索引.md"}:
            continue
        text = md.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        tweet_id = fm.get("tweet_id", "").strip()
        if not tweet_id:
            continue

        title = fm.get("title") or md.stem
        created_at = fm.get("created_at", "").strip()
        source = fm.get("source", "").strip()
        author_handle = fm.get("author_handle", "").strip()
        author_name = fm.get("author_name", "").strip()

        domain_raw = fm.get("domain", "").strip()
        domain_parts = [p.strip() for p in domain_raw.split("/") if p.strip()]
        if not domain_parts:
            m = re.search(r"-\s*(?:领域|Domain):\s*\[\[[^|]+\|([^\]]+)\]\]", body)
            if m:
                domain_parts = [p.strip() for p in m.group(1).split("/") if p.strip()]
        domain_parts = normalize_domain_parts(domain_parts)

        content = section_content("\n" + body, "内容")
        if not content:
            content = section_content("\n" + body, "Content")

        media_block = section_content("\n" + body, "媒体")
        if not media_block:
            media_block = section_content("\n" + body, "Media")
        media_lines = parse_media_lines_from_block(media_block)

        tags = parse_yaml_inline_list(fm.get("tags", ""))
        topic_tags = sorted({t for t in tags if t.startswith("topic/")})
        domain_tag = next((t for t in tags if t.startswith("domain/")), domain_tag_from_parts(domain_parts))

        out[tweet_id] = Record(
            tweet_id=tweet_id,
            title=title,
            author_handle=author_handle,
            author_name=author_name,
            created_at=created_at,
            source=source,
            domain_parts=domain_parts,
            domain_tag=domain_tag,
            topic_tags=topic_tags,
            favorite_count=int(fm.get("favorite_count", "0") or 0),
            retweet_count=int(fm.get("retweet_count", "0") or 0),
            reply_count=int(fm.get("reply_count", "0") or 0),
            quote_count=int(fm.get("quote_count", "0") or 0),
            bookmark_count=int(fm.get("bookmark_count", "0") or 0),
            views_count=int(fm.get("views_count", "0") or 0),
            content=content,
            media_lines=media_lines,
        )

    return out


def parse_json_records(
    json_path: Path,
    classification: str,
    manual_rules: Optional[Dict[str, object]],
) -> Dict[str, Record]:
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    by_id: Dict[str, Record] = {}

    for item in rows:
        if not isinstance(item, dict) or "id" not in item:
            continue

        tweet_id = str(item["id"])
        created_raw = str(item.get("created_at", "")).strip()
        date = created_raw[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", created_raw) else "1970-01-01"

        full_text = str(item.get("full_text", "")).replace("\r\n", "\n").strip()
        title = normalize_title(full_text, fallback_post_title(tweet_id))
        source = str(item.get("url") or f"https://x.com/i/web/status/{tweet_id}")

        media = as_list(item.get("media"))
        media_lines: List[str] = []
        for i, m in enumerate(media):
            md = as_dict(m)
            original = md.get("original") or md.get("thumbnail") or md.get("url")
            media_type = md.get("type") or "media"
            if original:
                media_lines.append(f"- {media_type} {i + 1}: {original}")

        if classification == "auto":
            domain_parts, domain_tag, topics = auto_classify(item, title, full_text, source)
        else:
            assert manual_rules is not None
            domain_parts, domain_tag, topics = manual_classify(title, full_text, source, manual_rules, media_lines)

        domain_parts = normalize_domain_parts(domain_parts)
        if not domain_tag.startswith("domain/"):
            domain_tag = domain_tag_from_parts(domain_parts)

        by_id[tweet_id] = Record(
            tweet_id=tweet_id,
            title=title,
            author_handle=str(item.get("screen_name", "")).strip(),
            author_name=str(item.get("name", "")).strip(),
            created_at=created_raw or date,
            source=source,
            domain_parts=domain_parts,
            domain_tag=domain_tag,
            topic_tags=topics,
            favorite_count=int(item.get("favorite_count", 0) or 0),
            retweet_count=int(item.get("retweet_count", 0) or 0),
            reply_count=int(item.get("reply_count", 0) or 0),
            quote_count=int(item.get("quote_count", 0) or 0),
            bookmark_count=int(item.get("bookmark_count", 0) or 0),
            views_count=int(item.get("views_count", 0) or 0),
            content=full_text,
            media_lines=media_lines,
        )

    return by_id


def month_name(date_str: str) -> str:
    return month_label_from_number(month_number(date_str))


def year_name(date_str: str) -> str:
    if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:4]
    return "1970"


def unique_note_path(dir_path: Path, base: str) -> Path:
    base = sanitize_filename(base) or t("untitled")
    candidate = dir_path / f"{base}.md"
    n = 2
    while candidate.exists():
        candidate = dir_path / f"{base} ({n}).md"
        n += 1
    return candidate


def reclassify_records_auto(records: Dict[str, Record]) -> None:
    for rec in records.values():
        parts, tag, topics = auto_classify({}, rec.title, rec.content, rec.source)
        rec.domain_parts = normalize_domain_parts(parts)
        rec.domain_tag = domain_tag_from_parts(rec.domain_parts) if not tag.startswith("domain/") else tag
        rec.topic_tags = sorted(set(rec.topic_tags + topics))


def reclassify_records_manual(records: Dict[str, Record], rules: Dict[str, object]) -> None:
    for rec in records.values():
        parts, tag, topics = manual_classify(rec.title, rec.content, rec.source, rules, rec.media_lines)
        rec.domain_parts = normalize_domain_parts(parts)
        rec.domain_tag = domain_tag_from_parts(rec.domain_parts) if not tag.startswith("domain/") else tag
        rec.topic_tags = sorted(set(topics))


def keyword_label(text: str, rules: Sequence[Tuple[str, Sequence[str]]], fallback: str) -> str:
    for label, kws in rules:
        if has_any(text, [k.lower() for k in kws]):
            return label
    return fallback
def infer_split_label(record: Record, parent_parts: Sequence[str]) -> str:
    text = f"{record.title}\n{record.content}\n{record.source}".lower()
    top = parent_parts[0] if parent_parts else "其他"
    leaf_name = parent_parts[-1] if parent_parts else "其他"

    if top == "AI":
        if leaf_name == "产品与应用":
            rules = [
                ("编程助手", ["claude code", "cursor", "copilot", "aider", "code", "编程", "开发"]),
                ("Agent与自动化", ["agent", "mcp", "workflow", "自动化", "hook", "pipeline"]),
                ("模型与提示词", ["prompt", "token", "rag", "模型", "提示词", "embedding"]),
                ("图像与视频", ["midjourney", "comfyui", "sora", "runway", "图像", "视频", "文生图"]),
                ("资讯与研究", ["research", "paper", "benchmark", "arxiv", "论文", "评测"]),
                ("效率应用", ["笔记", "写作", "总结", "翻译", "pdf", "ppt"]),
            ]
            return keyword_label(text, rules, "其他AI主题")

        rules = [
            ("编程助手", ["claude code", "cursor", "copilot", "aider", "code", "编程", "开发"]),
            ("Agent与自动化", ["agent", "mcp", "workflow", "自动化", "hook", "pipeline"]),
            ("模型与提示词", ["prompt", "token", "rag", "模型", "提示词", "embedding"]),
            ("图像与视频", ["midjourney", "comfyui", "sora", "runway", "图像", "视频", "文生图"]),
            ("资讯与研究", ["research", "paper", "benchmark", "arxiv", "论文", "评测"]),
            ("产品与应用", ["chatgpt", "claude", "gemini", "notebooklm", "assistant", "应用", "产品"]),
            ("效率应用", ["笔记", "写作", "总结", "翻译", "pdf", "ppt"]),
        ]
        return keyword_label(text, rules, "其他AI主题")

    if top == "技术与开发":
        if leaf_name in {"编程与开源", "开源仓库", "其他技术"}:
            rules = [
                ("AI编程", ["claude code", "cursor", "copilot", "aider", "ai coding", "编程助手"]),
                ("前端与交互", ["react", "vue", "css", "frontend", "前端", "页面", "web"]),
                ("后端与系统", ["api", "backend", "server", "数据库", "后端", "系统", "架构"]),
                ("DevOps与部署", ["docker", "k8s", "deploy", "devops", "运维", "部署", "ci/cd"]),
                ("语言与框架", ["python", "javascript", "typescript", "rust", "go", "framework", "库"]),
                ("开源仓库", ["github", "repo", "open source", "开源", "star"]),
            ]
            return keyword_label(text, rules, "其他技术")

        rules = [
            ("开源仓库", ["github", "repo", "open source", "开源", "star"]),
            ("工程实践", ["architecture", "system", "infra", "工程", "架构", "实现", "项目"]),
            ("教程文档", ["guide", "tutorial", "docs", "教程", "文档", "入门"]),
            ("工具链", ["cli", "terminal", "toolchain", "构建", "编译", "部署"]),
        ]
        return keyword_label(text, rules, "其他技术")

    if top == "工具与效率":
        rules = [
            ("笔记与知识管理", ["obsidian", "notion", "logseq", "笔记", "知识库"]),
            ("自动化流程", ["workflow", "automation", "zapier", "n8n", "自动化", "流程"]),
            ("应用工具", ["app", "plugin", "extension", "工具", "插件"]),
            ("方法与实践", ["productivity", "效率", "习惯", "方法", "系统"]),
        ]
        return keyword_label(text, rules, "其他工具")

    if top == "学习与教育":
        rules = [
            ("英语与语言", ["english", "ielts", "雅思", "英语", "词汇", "口语", "语法"]),
            ("课程与教程", ["course", "tutorial", "lesson", "课程", "教程", "讲解"]),
            ("考试与备考", ["exam", "test", "真题", "考试", "备考"]),
            ("认知与方法", ["learning method", "认知", "方法论", "思维", "学习法"]),
        ]
        return keyword_label(text, rules, "其他学习")

    if top == "社会与公共议题":
        rules = [
            ("政治与政策", ["politics", "policy", "government", "election", "政治", "政策", "政府", "选举"]),
            ("经济与宏观", ["economy", "macro", "gdp", "inflation", "经济", "宏观", "通胀", "利率"]),
            ("社会观察", ["society", "culture", "trend", "观点", "观察", "社会"]),
        ]
        return keyword_label(text, rules, "其他公共议题")

    if top == "文化与娱乐":
        rules = [
            ("书籍与阅读", ["book", "books", "reading", "kindle", "书", "书籍", "阅读", "书单"]),
            ("娱乐与八卦", ["gossip", "celebrity", "八卦", "明星", "绯闻", "吃瓜"]),
            ("影视与内容", ["movie", "tv", "video", "podcast", "影视", "视频", "播客"]),
        ]
        return keyword_label(text, rules, "其他文化")

    if top == "商业与经济":
        rules = [
            ("宏观经济", ["economy", "macro", "gdp", "inflation", "经济", "宏观", "通胀"]),
            ("商业增长", ["growth", "marketing", "运营", "增长", "营销", "流量"]),
            ("职场与管理", ["career", "management", "职场", "管理", "团队", "面试"]),
            ("创业与产品", ["startup", "创业", "产品", "saas", "商业模式"]),
        ]
        return keyword_label(text, rules, "其他商业")

    if top == "其他":
        rules = [
            ("技术与开发", ["github", "code", "api", "开源", "编程", "开发", "python", "javascript", "linux"]),
            ("AI", ["ai", "llm", "gpt", "claude", "gemini", "openai", "大模型", "模型"]),
            ("工具与效率", ["obsidian", "notion", "工具", "效率", "插件", "workflow"]),
            ("学习与教育", ["learning", "course", "tutorial", "学习", "教程", "课程", "英语", "雅思"]),
            ("健康与生活", ["health", "sleep", "fitness", "心理", "健康", "饮食", "运动"]),
            ("设计与创意", ["figma", "design", "ui", "ux", "设计", "视觉", "排版"]),
            ("金融与投资", ["investment", "finance", "crypto", "bitcoin", "投资", "金融", "股票", "基金"]),
            ("文化与娱乐", ["book", "books", "reading", "八卦", "明星", "娱乐", "书", "阅读", "书单"]),
            ("社会与公共议题", ["politics", "policy", "government", "政治", "政策", "社会", "观点"]),
            ("商业与经济", ["business", "startup", "marketing", "商业", "创业", "增长", "运营"]),
        ]
        return keyword_label(text, rules, "其他主题")

    rules = [
        ("教程与指南", ["guide", "how to", "教程", "指南", "步骤", "入门"]),
        ("工具与资源", ["tool", "plugin", "resources", "工具", "资源", "插件", "合集", "markdown", "rss", "vps", "tailscale", "文档", "生成器", "客户端", "主题", "模板"]),
        ("产品与应用", ["product", "app", "service", "产品", "应用", "平台", "openclaw", "clawhub", "minis"]),
        ("资讯与观点", ["news", "release", "update", "发布", "更新", "观点", "趋势", "横评", "评价", "政策"]),
        ("案例与实践", ["case", "practice", "project", "实践", "案例", "实现", "实战", "配置", "搭建", "调试", "debug"]),
        ("清单与收藏", ["list", "collection", "清单", "合集", "收藏", "整理了一些", "汇总"]),
    ]
    return keyword_label(text, rules, "其他主题")


def infer_content_bucket(record: Record) -> str:
    text = f"{record.title}\n{record.content}".lower()
    text_wo_urls = re.sub(r"https?://\S+", " ", text)
    text_wo_urls = re.sub(r"\s+", " ", text_wo_urls).strip()
    url_count = len(re.findall(r"https?://\S+", text))
    n = len(text_wo_urls)

    if has_any(text, ["github", "code", "api", "开源", "编程", "开发", "vps", "tailscale", "server", "rss", "debug", "ghostty", "内网穿透", "terminal", "前端", "后端", "程序员"]):
        return "代码技术"
    if has_any(text, ["learning", "course", "tutorial", "学习", "教程", "课程", "英语"]):
        return "学习资料"
    if has_any(text, ["tool", "plugin", "obsidian", "notion", "工具", "插件", "效率", "markdown", "ppt", "pdf", "文档", "生成器", "客户端", "模板", "主题"]):
        return "工具应用"
    if has_any(text, ["book", "books", "reading", "书", "阅读", "书单"]):
        return "书籍阅读"
    if has_any(text, ["gossip", "celebrity", "八卦", "明星", "绯闻", "吃瓜"]):
        return "娱乐八卦"
    if has_any(text, ["politics", "policy", "government", "政治", "政策"]):
        return "政治政策"
    if has_any(text, ["economy", "macro", "gdp", "经济", "宏观", "通胀", "bitcoin", "btc", "比特币"]):
        return "经济宏观"
    if has_any(text, ["health", "sleep", "fitness", "健康", "睡眠", "运动", "抑郁", "焦虑", "心理"]):
        return "健康生活"

    if url_count >= 1 and n <= 8:
        return "链接收藏"
    if record.media_lines and n <= 24:
        return "图像媒体"
    if n <= 30:
        return "短帖观点"
    if n <= 80:
        return "中短内容"
    if n <= 180:
        return "中篇内容"
    return "长文资料"

def infer_secondary_bucket(record: Record, leaf_parts: Sequence[str]) -> str:
    text = f"{record.title}\n{record.content}".lower()
    text_wo_urls = re.sub(r"https?://\S+", " ", text)
    text_wo_urls = re.sub(r"\s+", " ", text_wo_urls).strip()
    n = len(text_wo_urls)
    url_count = len(re.findall(r"https?://\S+", text))
    has_zh = bool(re.search(r"[\u4e00-\u9fff]", text_wo_urls))
    leaf = leaf_parts[-1] if leaf_parts else ""
    top = leaf_parts[0] if leaf_parts else ""

    if leaf in {"中段内容", "短文内容", "中短内容", "中篇内容"}:
        if has_any(text, ["github", "code", "api", "开源", "编程", "开发", "vps", "tailscale", "server", "rss", "ghostty", "terminal"]):
            return "技术向内容"
        if has_any(text, ["tool", "plugin", "obsidian", "notion", "工具", "插件", "效率", "markdown", "ppt", "pdf", "生成器", "文档"]):
            return "工具向内容"
        if has_any(text, ["learning", "course", "tutorial", "学习", "教程", "课程", "英语"]):
            return "学习向内容"
        if has_any(text, ["book", "books", "reading", "书", "阅读", "书单"]):
            return "书籍向内容"
        if has_any(text, ["politics", "policy", "government", "政治", "政策"]):
            return "公共议题内容"
        if url_count >= 1 and n <= 10:
            return "链接说明"
        if record.media_lines and n <= 30:
            return "图文说明"
        if n <= 35:
            return "极短观点"
        if n <= 70:
            return "短段内容"
        return "中文段落" if has_zh else "英文段落"

    if leaf == "开源仓库":
        rules = [
            ("AI项目", ["ai", "llm", "gpt", "claude", "模型"]),
            ("前端项目", ["react", "vue", "css", "frontend", "前端"]),
            ("后端项目", ["backend", "server", "api", "后端", "服务"]),
            ("数据项目", ["data", "dataset", "sql", "数据", "分析"]),
            ("运维项目", ["docker", "k8s", "deploy", "devops", "运维", "部署"]),
        ]
        return keyword_label(text, rules, "其他仓库")

    if top == "工具与效率" and leaf in {"应用工具", "工具应用", "其他工具", "中文内容", "英文内容", "通用工具", "主题杂项"}:
        rules = [
            ("笔记工具", ["obsidian", "notion", "logseq", "笔记"]),
            ("自动化工具", ["automation", "workflow", "n8n", "zapier", "自动化", "流程"]),
            ("浏览器工具", ["chrome", "extension", "浏览器", "插件"]),
            ("桌面工具", ["mac", "windows", "desktop", "客户端", "桌面"]),
            ("移动工具", ["ios", "android", "iphone", "ipad", "手机"]),
        ]
        out = keyword_label(text, rules, "")
        if out:
            return out
        if url_count >= 1 and n <= 10:
            return "链接工具"
        return "中文工具" if has_zh else "英文工具"

    if top == "技术与开发" and leaf in {"主题杂项", "其他技术", "中文内容", "英文内容", "中段内容", "短文内容"}:
        rules = [
            ("AI编程", ["claude code", "cursor", "copilot", "aider", "ai coding", "编程助手"]),
            ("前端与交互", ["react", "vue", "css", "frontend", "前端"]),
            ("后端与系统", ["backend", "server", "api", "后端", "服务", "数据库"]),
            ("DevOps与部署", ["docker", "k8s", "deploy", "devops", "运维", "部署"]),
            ("语言与框架", ["python", "javascript", "typescript", "rust", "go", "framework", "库"]),
        ]
        out = keyword_label(text, rules, "")
        if out:
            return out
        if url_count >= 1 and n <= 10:
            return "链接技术"
        return "中文技术" if has_zh else "英文技术"

    if leaf in {"主题杂项", "其他主题", "其他技术", "其他AI主题", "中文内容", "英文内容", "短帖观点"}:
        if has_any(text, ["github", "code", "api", "开源", "编程", "开发", "vps", "tailscale", "server", "rss", "ghostty", "terminal"]):
            return "代码技术"
        if has_any(text, ["learning", "course", "tutorial", "学习", "教程", "课程", "英语"]):
            return "学习资料"
        if has_any(text, ["tool", "plugin", "obsidian", "notion", "工具", "插件", "效率", "markdown", "ppt", "pdf", "文档", "生成器"]):
            return "工具应用"
        if has_any(text, ["book", "books", "reading", "书", "阅读", "书单"]):
            return "书籍阅读"
        if has_any(text, ["gossip", "celebrity", "八卦", "明星", "绯闻", "吃瓜"]):
            return "娱乐八卦"
        if has_any(text, ["politics", "policy", "government", "政治", "政策"]):
            return "政治政策"
        if has_any(text, ["economy", "macro", "gdp", "经济", "宏观", "通胀", "bitcoin", "btc", "比特币"]):
            return "经济宏观"
        if has_any(text, ["health", "sleep", "fitness", "健康", "睡眠", "运动", "抑郁", "焦虑", "心理"]):
            return "健康生活"

        if url_count >= 1 and n <= 8:
            return "链接收藏"
        if record.media_lines and n <= 24:
            return "图像媒体"
        if n <= 18:
            return "极短观点"
        if n <= 45:
            return "短文内容"
        if n <= 100:
            return "中段内容"
        return "中文长文" if has_zh else "英文长文"

    if url_count >= 1 and n <= 8:
        return "链接收藏"
    if record.media_lines and n <= 24:
        return "图像媒体"
    if n <= 40:
        return "短帖观点"
    return "中文内容" if has_zh else "英文内容"


def infer_profile_bucket(record: Record) -> str:
    text = f"{record.title}\n{record.content}".lower()
    text_wo_urls = re.sub(r"https?://\S+", " ", text)
    text_wo_urls = re.sub(r"\s+", " ", text_wo_urls).strip()
    n = len(text_wo_urls)
    url_count = len(re.findall(r"https?://\S+", text))
    has_zh = bool(re.search(r"[\u4e00-\u9fff]", text_wo_urls))

    theme = "综合"
    if has_any(text, ["github", "code", "api", "开源", "编程", "开发", "vps", "tailscale", "server", "rss", "ghostty", "terminal"]):
        theme = "技术"
    elif has_any(text, ["learning", "course", "tutorial", "学习", "教程", "课程", "英语"]):
        theme = "学习"
    elif has_any(text, ["tool", "plugin", "obsidian", "notion", "工具", "插件", "效率", "markdown", "ppt", "pdf", "文档", "生成器"]):
        theme = "工具"
    elif has_any(text, ["investment", "finance", "crypto", "bitcoin", "btc", "投资", "金融", "股票", "基金", "比特币"]):
        theme = "金融"
    elif has_any(text, ["book", "books", "reading", "八卦", "明星", "书", "阅读", "娱乐", "抑郁", "焦虑", "心理"]):
        theme = "文化"

    lang = "中文" if has_zh else "英文"
    if url_count >= 1 and n <= 8:
        form = "链接"
    elif record.media_lines and n <= 24:
        form = "图文"
    elif n <= 35:
        form = "短"
    elif n <= 110:
        form = "中"
    else:
        form = "长"

    return f"{theme}-{lang}-{form}"

def infer_fine_bucket(record: Record) -> str:
    text = f"{record.title}\n{record.content}".lower()
    text_wo_urls = re.sub(r"https?://\S+", " ", text)
    text_wo_urls = re.sub(r"\s+", " ", text_wo_urls).strip()
    n = len(text_wo_urls)
    url_count = len(re.findall(r"https?://\S+", text))
    has_zh = bool(re.search(r"[\u4e00-\u9fff]", text_wo_urls))

    theme = "综合"
    if has_any(text, ["github", "code", "api", "开源", "编程", "开发", "vps", "tailscale", "server", "rss", "ghostty", "terminal"]):
        theme = "技术"
    elif has_any(text, ["learning", "course", "tutorial", "学习", "教程", "课程", "英语"]):
        theme = "学习"
    elif has_any(text, ["tool", "plugin", "obsidian", "notion", "工具", "插件", "效率", "markdown", "ppt", "pdf", "文档", "生成器"]):
        theme = "工具"
    elif has_any(text, ["investment", "finance", "crypto", "bitcoin", "btc", "投资", "金融", "股票", "基金", "比特币"]):
        theme = "金融"
    elif has_any(text, ["book", "books", "reading", "八卦", "明星", "书", "阅读", "娱乐", "抑郁", "焦虑", "心理"]):
        theme = "文化"

    lang = "中文" if has_zh else "英文"
    if url_count >= 1 and n <= 8:
        form = "链接"
    elif record.media_lines and n <= 24:
        form = "图文"
    elif n <= 24:
        form = "极短"
    elif n <= 45:
        form = "短"
    elif n <= 90:
        form = "中"
    elif n <= 160:
        form = "中长"
    else:
        form = "长"

    if n <= 10:
        band = "L1"
    elif n <= 20:
        band = "L2"
    elif n <= 35:
        band = "L3"
    elif n <= 55:
        band = "L4"
    elif n <= 80:
        band = "L5"
    elif n <= 120:
        band = "L6"
    else:
        band = "L7"

    return f"{theme}-{lang}-{form}-{band}"
def rebalance_domains(records: Dict[str, Record], max_size: int = MAX_DOMAIN_FILE_SIZE, max_depth: int = MAX_DOMAIN_DEPTH) -> None:
    for rec in records.values():
        rec.domain_parts = normalize_domain_parts(rec.domain_parts)
        rec.domain_tag = domain_tag_from_parts(rec.domain_parts)

    max_rounds = max_depth * 5
    fallback_labels = {
        "其他主题",
        "其他AI主题",
        "其他公共议题",
        "其他文化",
        "其他商业",
        "其他技术",
        "其他工具",
        "其他学习",
        "主题杂项",
    }

    def run_split(
        rows: Sequence[Record],
        label_fn,
        leaf_last: str,
        ignore_fallback: bool,
        threshold_base: int,
        divisor: int,
    ) -> Tuple[Dict[str, str], Dict[str, int], List[str]]:
        label_by_id: Dict[str, str] = {}
        labels: Dict[str, int] = {}
        for rec in rows:
            lb = str(label_fn(rec)).strip() or "主题杂项"
            label_by_id[rec.tweet_id] = lb
            labels[lb] = labels.get(lb, 0) + 1

        threshold = max(threshold_base, len(rows) // divisor)
        major = []
        for k, v in labels.items():
            if v < threshold:
                continue
            if k == leaf_last:
                continue
            if ignore_fallback and k in fallback_labels:
                continue
            major.append(k)

        if len(major) < 2:
            candidates = []
            for k, v in labels.items():
                if k == leaf_last:
                    continue
                if ignore_fallback and k in fallback_labels:
                    continue
                candidates.append((k, v))
            candidates.sort(key=lambda kv: kv[1], reverse=True)
            major = [k for k, v in candidates[:4] if v >= 8]

        return label_by_id, labels, major

    for _ in range(max_rounds):
        by_leaf: Dict[Tuple[str, ...], List[Record]] = {}
        for rec in records.values():
            leaf = tuple(rec.domain_parts or ["其他"])
            by_leaf.setdefault(leaf, []).append(rec)

        oversized = [(leaf, rows) for leaf, rows in by_leaf.items() if len(rows) > max_size]
        if not oversized:
            break

        oversized.sort(key=lambda kv: len(kv[1]), reverse=True)
        changed = False

        for leaf, rows in oversized:
            if len(leaf) >= max_depth:
                continue

            leaf_last = leaf[-1]

            label_by_id, labels, major = run_split(
                rows,
                lambda r: infer_split_label(r, list(leaf)),
                leaf_last,
                True,
                10,
                14,
            )

            dominant = max(labels.values()) if labels else 0
            if len(major) < 2 or dominant >= int(len(rows) * 0.8):
                label_by_id, labels, major = run_split(
                    rows,
                    infer_content_bucket,
                    leaf_last,
                    False,
                    10,
                    12,
                )
                dominant = max(labels.values()) if labels else 0

            if len(major) < 2 or dominant >= int(len(rows) * 0.75):
                label_by_id, labels, major = run_split(
                    rows,
                    lambda r: infer_secondary_bucket(r, list(leaf)),
                    leaf_last,
                    False,
                    8,
                    10,
                )
                dominant = max(labels.values()) if labels else 0

            if len(major) < 2 or dominant >= int(len(rows) * 0.7):
                label_by_id, labels, major = run_split(
                    rows,
                    infer_profile_bucket,
                    leaf_last,
                    False,
                    6,
                    20,
                )

            if len(major) < 2:
                continue
                continue

            major_total = sum(labels.get(k, 0) for k in major)
            if major_total < max(30, len(rows) // 5):
                continue

            major_set = set(major)
            for rec in rows:
                old_parts = rec.domain_parts[:]
                label = label_by_id.get(rec.tweet_id, "主题杂项")

                if label in major_set and label != leaf_last:
                    new_parts = normalize_domain_parts(list(leaf) + [label])
                else:
                    if leaf_last in fallback_labels:
                        new_parts = normalize_domain_parts(list(leaf))
                    else:
                        new_parts = normalize_domain_parts(list(leaf) + ["主题杂项"])

                if len(new_parts) > max_depth:
                    new_parts = new_parts[:max_depth]

                if new_parts != old_parts:
                    rec.domain_parts = new_parts
                    rec.domain_tag = domain_tag_from_parts(new_parts)
                    changed = True

        if not changed:
            break

    # Final enforcement pass: if any leaf is still > max_size, force a finer content-profile split.
    for _ in range(2):
        by_leaf = {}
        for rec in records.values():
            leaf = tuple(rec.domain_parts or ["其他"])
            by_leaf.setdefault(leaf, []).append(rec)

        oversized = [(leaf, rows) for leaf, rows in by_leaf.items() if len(rows) > max_size]
        if not oversized:
            break

        force_changed = False
        for leaf, rows in oversized:
            if len(leaf) >= max_depth:
                continue
            bucket_by_id = {}
            bucket_count = {}
            for rec in rows:
                b = infer_fine_bucket(rec)
                bucket_by_id[rec.tweet_id] = b
                bucket_count[b] = bucket_count.get(b, 0) + 1
            if len(bucket_count) < 2:
                continue
            for rec in rows:
                old_parts = rec.domain_parts[:]
                b = bucket_by_id.get(rec.tweet_id, "综合-中文-中-L5")
                new_parts = normalize_domain_parts(list(leaf) + [b])
                if len(new_parts) > max_depth:
                    new_parts = new_parts[:max_depth]
                if new_parts != old_parts:
                    rec.domain_parts = new_parts
                    rec.domain_tag = domain_tag_from_parts(new_parts)
                    force_changed = True
        if not force_changed:
            break
    top_domains = sorted({(rec.domain_parts[0] if rec.domain_parts else "其他") for rec in records.values()})
    if len(top_domains) > MAX_TOP_LEVEL_DOMAINS:
        keep = set(TOP_DOMAIN_ORDER[:MAX_TOP_LEVEL_DOMAINS])
        for rec in records.values():
            if not rec.domain_parts:
                rec.domain_parts = ["其他"]
            if rec.domain_parts[0] not in keep:
                rec.domain_parts = ["其他"] + rec.domain_parts[1:]
            rec.domain_parts = normalize_domain_parts(rec.domain_parts)
            rec.domain_tag = domain_tag_from_parts(rec.domain_parts)
def build_note_text(
    record: Record,
    title: str,
    domain_parts: List[str],
    tags: List[str],
) -> str:
    domain_label = "/".join(domain_parts)
    domain_display = "/".join(localize_domain_parts(domain_parts))
    domain_link = domain_rel_link(domain_parts)

    author_display = t("unknown_author")
    if record.author_name and record.author_handle:
        author_display = f"{record.author_name} ({record.author_handle})"
    elif record.author_name:
        author_display = record.author_name
    elif record.author_handle:
        author_display = record.author_handle

    media_lines = record.media_lines if record.media_lines else [t("none_media")]

    return "\n".join(
        [
            "---",
            f"tweet_id: {quote_yaml(record.tweet_id)}",
            f"title: {quote_yaml(title)}",
            f"author_handle: {quote_yaml(record.author_handle)}",
            f"author_name: {quote_yaml(record.author_name)}",
            f"created_at: {quote_yaml(record.created_at)}",
            f"source: {quote_yaml(record.source)}",
            f"domain: {quote_yaml(domain_label)}",
            f"favorite_count: {record.favorite_count}",
            f"retweet_count: {record.retweet_count}",
            f"reply_count: {record.reply_count}",
            f"quote_count: {record.quote_count}",
            f"bookmark_count: {record.bookmark_count}",
            f"views_count: {record.views_count}",
            "tags: [" + ", ".join(quote_yaml(t) for t in tags) + "]",
            f"imported_at: {quote_yaml('generated-by-convert-x-likes-to-markdown')}",
            "---",
            "",
            f"# {title}",
            "",
            f"- {t('field_author')}: {author_display}",
            f"- {t('field_created_at')}: {record.created_at}",
            f"- {t('field_source')}: {record.source}",
            f"- {t('field_domain')}: [[{domain_link}|{domain_display}]]",
            "",
            f"## {t('section_content')}",
            "",
            record.content or t("empty_content"),
            "",
            f"## {t('section_media')}",
            "",
            *media_lines,
            "",
        ]
    )


def render_structure(stage_root: Path, records: Dict[str, Record]) -> Dict[str, object]:
    date_root = stage_root / root_date_name()
    author_root = stage_root / root_author_name()
    domain_root = stage_root / root_domain_name()

    for d in (date_root, author_root, domain_root):
        d.mkdir(parents=True, exist_ok=True)

    sorted_records = sorted(
        records.values(),
        key=lambda r: (
            (r.created_at[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", r.created_at) else "1970-01-01"),
            r.tweet_id,
        ),
        reverse=True,
    )

    note_rows: List[Dict[str, object]] = []
    url_rows: List[str] = []

    for rec in sorted_records:
        yr = year_name(rec.created_at)
        mn = month_number(rec.created_at)
        mo = month_label_from_number(mn)
        note_dir = date_root / yr / mo
        note_dir.mkdir(parents=True, exist_ok=True)

        domain_parts = normalize_domain_parts(rec.domain_parts if rec.domain_parts else ["其他"])
        title = normalize_title(rec.title, fallback_post_title(rec.tweet_id))
        note_path = unique_note_path(note_dir, title)

        tags = ["x-like", rec.domain_tag or domain_tag_from_parts(domain_parts), f"year/{yr}"]
        if re.match(r"^\d{4}-\d{2}-\d{2}", rec.created_at):
            tags.append(f"month/{int(rec.created_at[5:7])}")
        tags.extend(rec.topic_tags)
        tags = sorted(set(tags))[:12]

        note_text = build_note_text(rec, note_path.stem, domain_parts, tags)
        note_path.write_text(note_text, encoding="utf-8")

        rel = note_path.relative_to(stage_root).as_posix()
        note_rows.append(
            {
                "tweet_id": rec.tweet_id,
                "title": note_path.stem,
                "author": rec.author_name or rec.author_handle or t("unknown_author"),
                "author_handle": rec.author_handle or t("unknown_author"),
                "created_at": rec.created_at,
                "year": yr,
                "month": mo,
                "month_num": mn,
                "domain": "/".join(domain_parts),
                "domain_top": domain_parts[0],
                "rel_path": rel,
                "domain_link": domain_rel_link(domain_parts),
                "url": rec.source,
            }
        )
        url_rows.append(rec.source)

    # Date indexes
    by_year: Dict[str, List[Dict[str, object]]] = {}
    for row in note_rows:
        by_year.setdefault(str(row["year"]), []).append(row)

    for year, rows in by_year.items():
        month_map: Dict[int, List[Dict[str, object]]] = {}
        for r in rows:
            month_map.setdefault(int(r.get("month_num", 0) or 0), []).append(r)

        month_order = sorted(month_map.keys(), reverse=True)

        year_lines = [
            "---",
            f"year: {year}",
            f"count: {len(rows)}",
            'tags: ["x-like", "index/year"]',
            "---",
            "",
            f"# {year}",
            "",
            f"{t('label_total')}: **{len(rows)}**",
            "",
            f"## {t('section_months')}",
            "",
        ]

        for month_num in month_order:
            month_rows = month_map[month_num]
            month_rows.sort(key=lambda r: (str(r["created_at"]), str(r["tweet_id"])), reverse=True)
            month_label = month_label_from_number(month_num)
            month_dir = date_root / year / month_label
            month_dir.mkdir(parents=True, exist_ok=True)

            month_lines = [
                "---",
                f"year: {year}",
                f"month: {quote_yaml(month_label)}",
                f"count: {len(month_rows)}",
                'tags: ["x-like", "index/month"]',
                "---",
                "",
                f"# {year} / {month_label}",
                "",
                f"{t('label_total')}: **{len(month_rows)}**",
                "",
                f"## {t('section_notes')}",
                "",
            ]
            for r in month_rows:
                month_lines.append(f"- [[{r['rel_path']}|{r['title']}]]")
            month_lines.append("")
            (month_dir / index_name()).write_text("\n".join(month_lines), encoding="utf-8")

            year_lines.append(f"- [[{root_date_name()}/{year}/{month_label}/{index_stem()}|{month_label}]] ({len(month_rows)})")

        year_lines.append("")
        (date_root / year / index_name()).write_text("\n".join(year_lines), encoding="utf-8")

    year_order = sorted(by_year.keys(), reverse=True)
    date_index_lines = [
        "---",
        f"count: {len(note_rows)}",
        f"years: {len(year_order)}",
        'tags: ["x-like", "index/date"]',
        "---",
        "",
        f"# {t('title_date')}",
        "",
        f"{t('label_total')}: **{len(note_rows)}**",
        "",
        f"## {t('section_years')}",
        "",
    ]
    for y in year_order:
        date_index_lines.append(f"- [[{root_date_name()}/{y}/{index_stem()}|{y}]] ({len(by_year[y])})")
    date_index_lines.append("")
    (date_root / index_name()).write_text("\n".join(date_index_lines), encoding="utf-8")

    # Author indexes
    by_author: Dict[str, List[Dict[str, object]]] = {}
    for r in note_rows:
        by_author.setdefault(str(r["author_handle"]), []).append(r)

    for handle, rows in by_author.items():
        rows.sort(key=lambda r: (str(r["created_at"]), str(r["tweet_id"])), reverse=True)
        by_ym: Dict[Tuple[str, int], List[Dict[str, object]]] = {}
        for r in rows:
            by_ym.setdefault((str(r["year"]), int(r.get("month_num", 0) or 0)), []).append(r)

        ym_keys = sorted(by_ym.keys(), key=lambda ym: (ym[0], ym[1]), reverse=True)

        author_name = str(rows[0]["author"])
        lines = [
            "---",
            f"author_handle: {quote_yaml(handle)}",
            f"author_name: {quote_yaml(author_name)}",
            f"count: {len(rows)}",
            'tags: ["x-like", "index/author"]',
            "---",
            "",
            f"# {author_name}",
            "",
            f"{t('label_total')}: **{len(rows)}**",
            "",
        ]
        for yy, mm in ym_keys:
            ym_label = f"{yy} / {month_label_from_number(mm)}"
            lines.append(f"## {ym_label}")
            lines.append("")
            for r in by_ym[(yy, mm)]:
                lines.append(f"- [[{r['rel_path']}|{r['title']}]]")
            lines.append("")

        fname = sanitize_filename(handle) or t("unknown_author")
        (author_root / f"{fname}.md").write_text("\n".join(lines), encoding="utf-8")

    author_items = sorted(by_author.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    author_index_lines = [
        "---",
        f"count: {len(author_items)}",
        'tags: ["x-like", "index/author"]',
        "---",
        "",
        f"# {t('title_author')}",
        "",
        f"{t('label_total_authors')}: **{len(author_items)}**",
        "",
        f"## {t('section_list')}",
        "",
    ]
    for handle, rows in author_items:
        name = str(rows[0]["author"])
        author_index_lines.append(f"- [[{root_author_name()}/{sanitize_filename(handle)}|{name}]] ({len(rows)})")
    author_index_lines.append("")
    (author_root / index_name()).write_text("\n".join(author_index_lines), encoding="utf-8")

    # Domain leaf files
    by_domain: Dict[str, List[Dict[str, object]]] = {}
    for r in note_rows:
        by_domain.setdefault(str(r["domain"]), []).append(r)

    domain_items = sorted(by_domain.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    top_domain_counter: Dict[str, int] = {}

    for domain_key, rows in domain_items:
        parts = normalize_domain_parts([p for p in domain_key.split("/") if p])
        top = parts[0]
        top_domain_counter[top] = top_domain_counter.get(top, 0) + len(rows)

        rows.sort(key=lambda r: (str(r["created_at"]), str(r["tweet_id"])), reverse=True)
        by_ym: Dict[Tuple[str, int], List[Dict[str, object]]] = {}
        for r in rows:
            by_ym.setdefault((str(r["year"]), int(r.get("month_num", 0) or 0)), []).append(r)

        ym_keys = sorted(by_ym.keys(), key=lambda ym: (ym[0], ym[1]), reverse=True)

        domain_file = domain_abs_path(domain_root, parts)
        domain_display = "/".join(localize_domain_parts(parts))
        lines = [
            "---",
            f"domain: {quote_yaml('/'.join(parts))}",
            f"count: {len(rows)}",
            'tags: ["x-like", "index/domain"]',
            "---",
            "",
            f"# {domain_display}",
            "",
            f"{t('label_total')}: **{len(rows)}**",
            "",
        ]
        for yy, mm in ym_keys:
            ym_label = f"{yy} / {month_label_from_number(mm)}"
            lines.append(f"## {ym_label}")
            lines.append("")
            for r in by_ym[(yy, mm)]:
                lines.append(f"- [[{r['rel_path']}|{r['title']}]]")
            lines.append("")
        domain_file.write_text("\n".join(lines), encoding="utf-8")

    # Parent indexes for any hierarchical levels.
    parent_children: Dict[Tuple[str, ...], Dict[Tuple[str, ...], int]] = {}
    for domain_key, rows in domain_items:
        parts = normalize_domain_parts([p for p in domain_key.split("/") if p])
        for i in range(1, len(parts)):
            parent = tuple(parts[:i])
            child = tuple(parts[: i + 1])
            parent_children.setdefault(parent, {})
            parent_children[parent][child] = parent_children[parent].get(child, 0) + len(rows)

    for parent, child_map in sorted(parent_children.items(), key=lambda kv: kv[0]):
        child_entries = sorted(child_map.items(), key=lambda kv: (-kv[1], "/".join(kv[0])))
        parent_path = domain_parent_index_path(domain_root, list(parent))
        lines = [
            "---",
            f"domain: {quote_yaml('/'.join(parent))}",
            f"count: {sum(cnt for _, cnt in child_entries)}",
            'tags: ["x-like", "index/domain"]',
            "---",
            "",
            f"# {'/'.join(localize_domain_parts(parent))}",
            "",
            f"## {t('section_subcategories')}",
            "",
        ]
        for child, cnt in child_entries:
            child_name = "/".join(localize_domain_parts(child[len(parent) :]))
            if len(child_name) == 0:
                child_name = localize_domain_part(child[-1])
            child_link = domain_rel_link(child)
            # child may itself be a parent with index.
            if tuple(child) in parent_children:
                child_link = domain_parent_index_link(child)
            lines.append(f"- [[{child_link}|{child_name}]] ({cnt})")
        lines.append("")
        parent_path.write_text("\n".join(lines), encoding="utf-8")

    # Domain root index
    top_domains_sorted = sorted(top_domain_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    domain_root_lines = [
        "---",
        f"count: {len(top_domains_sorted)}",
        'tags: ["x-like", "index/domain"]',
        "---",
        "",
        f"# {t('title_domain')}",
        "",
        f"{t('label_total_domains')}: **{len(top_domains_sorted)}**",
        "",
        f"## {t('section_list')}",
        "",
    ]

    parent_keys = set(parent_children.keys())
    for top, cnt in top_domains_sorted:
        top_display = localize_domain_part(top)
        if (top,) in parent_keys:
            domain_root_lines.append(f"- [[{domain_parent_index_link([top])}|{top_display}]] ({cnt})")
        else:
            domain_root_lines.append(f"- [[{domain_rel_link([top])}|{top_display}]] ({cnt})")
    domain_root_lines.append("")
    (domain_root / index_name()).write_text("\n".join(domain_root_lines), encoding="utf-8")

    # Dashboard
    month_counter: Dict[Tuple[str, int], int] = {}
    for r in note_rows:
        key = (str(r["year"]), int(r.get("month_num", 0) or 0))
        month_counter[key] = month_counter.get(key, 0) + 1
    month_items = sorted(
        month_counter.items(),
        key=lambda kv: (kv[0][0], kv[0][1]),
        reverse=True,
    )

    dashboard_lines = [
        "---",
        f"count: {len(note_rows)}",
        'tags: ["x-like", "dashboard"]',
        "---",
        "",
        f"# {t('title_dashboard')}",
        "",
        f"{t('label_total')}: **{len(note_rows)}**",
        "",
        f"- [[{root_date_name()}/{index_stem()}|{t('title_date')}]]",
        f"- [[{root_author_name()}/{index_stem()}|{t('title_author')}]]",
        f"- [[{root_domain_name()}/{index_stem()}|{t('title_domain')}]]",
        "",
        f"## {t('section_month_stats')}",
        "",
    ]
    for (y, mnum), cnt in month_items:
        month_label = month_label_from_number(mnum)
        ym = f"{y} / {month_label}"
        dashboard_lines.append(f"- [[{root_date_name()}/{y}/{month_label}/{index_stem()}|{ym}]]: {cnt}")

    dashboard_lines.extend(["", f"## {t('section_domain_stats')}", ""])
    for top, cnt in top_domains_sorted:
        top_display = localize_domain_part(top)
        if (top,) in parent_keys:
            dashboard_lines.append(f"- [[{domain_parent_index_link([top])}|{top_display}]]: {cnt}")
        else:
            dashboard_lines.append(f"- [[{domain_rel_link([top])}|{top_display}]]: {cnt}")

    dashboard_lines.extend(["", f"## {t('section_urls')}", "", "<details>"])
    dashboard_lines.append(f"<summary>{t('summary_show_all_urls').format(count=len(url_rows))}</summary>")
    dashboard_lines.append("")
    dashboard_lines.extend(url_rows)
    dashboard_lines.extend(["", "</details>", ""])
    (stage_root / dashboard_name()).write_text("\n".join(dashboard_lines), encoding="utf-8")

    max_domain_leaf_size = max((len(rows) for rows in by_domain.values()), default=0)
    max_domain_depth = max((len(k.split("/")) for k in by_domain.keys()), default=1)
    top_domain_count = len(top_domains_sorted)
    oversized_leaf_count = sum(1 for rows in by_domain.values() if len(rows) > MAX_DOMAIN_FILE_SIZE)

    return {
        "note_rows": note_rows,
        "top_domains": top_domains_sorted,
        "month_items": [(f"{y} / {month_label_from_number(m)}", cnt) for (y, m), cnt in month_items],
        "url_count": len(url_rows),
        "max_domain_leaf_size": max_domain_leaf_size,
        "max_domain_depth": max_domain_depth,
        "top_domain_count": top_domain_count,
        "oversized_leaf_count": oversized_leaf_count,
    }


def replace_target(root_dir: Path, stage_root: Path) -> None:
    removable = {
        "10 By Date",
        "20 By Author",
        "30 By Domain",
        "00 Dashboard.md",
        "liked-urls.txt",
        "Index.md",
        "索引.md",
        "01 日期",
        "02 作者",
        "03 领域",
        "仪表盘.md",
    }
    for cfg in LANG_PACKS.values():
        removable.add(cfg["root_date"])
        removable.add(cfg["root_author"])
        removable.add(cfg["root_domain"])
        removable.add(cfg["dashboard_file"])
        removable.add(cfg["index_file"])

    for name in sorted(removable):
        p = root_dir / name
        if not p.exists():
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()

    shutil.copytree(stage_root / root_date_name(), root_dir / root_date_name())
    shutil.copytree(stage_root / root_author_name(), root_dir / root_author_name())
    shutil.copytree(stage_root / root_domain_name(), root_dir / root_domain_name())
    shutil.copy2(stage_root / dashboard_name(), root_dir / dashboard_name())
    (root_dir / root_search_name()).mkdir(parents=True, exist_ok=True)
    (root_dir / root_rubbish_name()).mkdir(parents=True, exist_ok=True)


def strip_duplicate_suffix(name: str) -> str:
    name = name.strip()
    match = re.match(r"^(.*?)(?:\s+\d+)$", name)
    if not match:
        return name
    return match.group(1).rstrip()


def normalize_year_folder(name: str) -> str:
    name = strip_duplicate_suffix(name)
    match = re.match(r"^(\d{4})(?:\s+\d+)?$", name)
    return match.group(1) if match else name


def normalize_month_folder(name: str) -> str:
    raw = strip_duplicate_suffix(name)
    month_map = {
        "jan": "1 月",
        "feb": "2 月",
        "mar": "3 月",
        "apr": "4 月",
        "may": "5 月",
        "jun": "6 月",
        "jul": "7 月",
        "aug": "8 月",
        "sep": "9 月",
        "oct": "10 月",
        "nov": "11 月",
        "dec": "12 月",
    }
    m = re.match(r"^(\d{1,2})\s*月$", raw)
    if m:
        return f"{int(m.group(1))} 月"
    return month_map.get(raw.lower(), raw)


def merge_path_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
        return
    if source.read_text(encoding="utf-8", errors="ignore") == target.read_text(encoding="utf-8", errors="ignore"):
        return
    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = target.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            shutil.copy2(source, candidate)
            return
        counter += 1


def normalize_date_tree(date_root: Path) -> None:
    if not date_root.exists():
        return

    year_dirs = [p for p in date_root.iterdir() if p.is_dir()]
    for year_dir in sorted(year_dirs):
        canonical_year = normalize_year_folder(year_dir.name)
        year_target = date_root / canonical_year
        if year_target != year_dir:
            year_target.mkdir(parents=True, exist_ok=True)
            for child in sorted(year_dir.iterdir()):
                if child.is_file():
                    merge_path_file(child, year_target / child.name)
                else:
                    canonical_month = normalize_month_folder(child.name)
                    month_target = year_target / canonical_month
                    month_target.mkdir(parents=True, exist_ok=True)
                    for item in sorted(child.iterdir()):
                        if item.is_file():
                            merge_path_file(item, month_target / item.name)
            shutil.rmtree(year_dir)

    for year_dir in sorted([p for p in date_root.iterdir() if p.is_dir()]):
        for month_dir in sorted([p for p in year_dir.iterdir() if p.is_dir()]):
            canonical_month = normalize_month_folder(month_dir.name)
            month_target = year_dir / canonical_month
            if month_target == month_dir:
                continue
            month_target.mkdir(parents=True, exist_ok=True)
            for item in sorted(month_dir.iterdir()):
                if item.is_file():
                    merge_path_file(item, month_target / item.name)
            shutil.rmtree(month_dir)


def existing_date_roots(root_dir: Path) -> List[Path]:
    names = {cfg["root_date"] for cfg in LANG_PACKS.values()} | {"01 Date", "01 日期"}
    roots = [root_dir / n for n in sorted(names) if (root_dir / n).exists()]
    if not roots:
        fallback = root_dir / root_date_name()
        if fallback.exists():
            roots.append(fallback)
    return roots


def validate_output(root_dir: Path, expected_notes: int) -> Tuple[int, int]:
    roots = existing_date_roots(root_dir)
    date_root = roots[0] if roots else root_dir / root_date_name()
    md_count = 0
    tweet_count = 0
    if not date_root.exists():
        return 0, 0

    for md in date_root.rglob("*.md"):
        md_count += 1
        if md.name in {cfg["index_file"] for cfg in LANG_PACKS.values()} | {"Index.md", "索引.md"}:
            continue
        text = md.read_text(encoding="utf-8")
        if re.search(r"^tweet_id:\s*\"?.+\"?\s*$", text, re.MULTILINE):
            tweet_count += 1

    if tweet_count != expected_notes:
        raise RuntimeError(
            f"tweet note count mismatch after write: {tweet_count} != expected {expected_notes}"
        )
    bad_years = [p.name for p in date_root.iterdir() if p.is_dir() and not re.fullmatch(r"\d{4}", p.name)]
    bad_months = []
    for year_dir in [p for p in date_root.iterdir() if p.is_dir()]:
        for month_dir in [p for p in year_dir.iterdir() if p.is_dir()]:
            if not re.fullmatch(r"\d{1,2} 月", month_dir.name):
                bad_months.append(f"{year_dir.name}/{month_dir.name}")
    if bad_years or bad_months:
        raise RuntimeError(
            f"date tree normalization failed; bad_years={bad_years[:10]} bad_months={bad_months[:10]}"
        )
    return md_count, tweet_count


def main() -> None:
    args = parse_args()
    set_active_language(args.title_language)

    input_json = Path(args.input_json).expanduser().resolve()
    target_root = Path(args.target_root).expanduser().resolve()
    output_root = target_root / args.container_name

    if not input_json.exists():
        raise FileNotFoundError(f"input JSON not found: {input_json}")

    if args.classification == "manual" and not args.manual_rules:
        raise ValueError("--manual-rules is required when --classification manual")

    manual_rules = None
    if args.classification == "manual":
        rules_path = Path(args.manual_rules).expanduser().resolve()
        if not rules_path.exists():
            raise FileNotFoundError(f"manual rules file not found: {rules_path}")
        manual_rules = load_manual_rules(rules_path)

    output_root.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Record] = {}
    if args.mode == "merge":
        for date_root in existing_date_roots(output_root):
            existing.update(parse_existing_records(date_root))

    incoming = parse_json_records(input_json, args.classification, manual_rules)

    if args.mode == "create":
        merged = incoming
    else:
        merged = dict(existing)
        merged.update(incoming)

    rubbish_ids = collect_rubbish_tweet_ids(output_root)
    apply_rubbish_filter(merged, rubbish_ids)

    # Always normalize domain names to merge semantically equivalent categories.
    for rec in merged.values():
        rec.domain_parts = normalize_domain_parts(rec.domain_parts)
        rec.domain_tag = domain_tag_from_parts(rec.domain_parts)

    # Explicit reclassification applies to the full merged archive, not only new records.
    if args.classification == "auto":
        reclassify_records_auto(merged)
    elif args.classification == "manual":
        assert manual_rules is not None
        reclassify_records_manual(merged, manual_rules)

    # File management rules: split oversized leaves with deeper hierarchy.
    rebalance_domains(merged, max_size=MAX_DOMAIN_FILE_SIZE, max_depth=MAX_DOMAIN_DEPTH)

    stage_parent = Path(tempfile.mkdtemp(prefix="xlikes-sync-"))
    stage_root = stage_parent / "X Likes"
    stage_root.mkdir(parents=True, exist_ok=True)

    try:
        render_result = render_structure(stage_root, merged)
        replace_target(output_root, stage_root)
        normalize_date_tree(output_root / root_date_name())
        md_count, tweet_count = validate_output(output_root, len(merged))
        clear_rubbish_folder(output_root)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)

    summary = {
        "input_json": str(input_json),
        "output_root": str(output_root),
        "mode": args.mode,
        "classification": args.classification,
        "title_language": args.title_language,
        "existing_before": len(existing),
        "incoming": len(incoming),
        "rubbish_removed": len(rubbish_ids),
        "final_notes": len(merged),
        "final_tweet_notes": tweet_count,
        "final_md_files_under_date": md_count,
        "top_domains": render_result["top_domains"],
        "top_domain_count": render_result["top_domain_count"],
        "month_stats": render_result["month_items"],
        "url_count": render_result["url_count"],
        "max_domain_leaf_size": render_result["max_domain_leaf_size"],
        "max_domain_depth": render_result["max_domain_depth"],
        "oversized_leaf_count": render_result["oversized_leaf_count"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
