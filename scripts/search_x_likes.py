#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass
class SearchRecord:
    title: str
    rel_path: Path
    tweet_id: str
    author_handle: str
    author_name: str
    created_at: str
    domain: str
    source: str
    content: str


def parse_frontmatter(note_path: Path) -> tuple[dict[str, str], str]:
    text = note_path.read_text(encoding="utf-8", errors="ignore")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    values: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip().strip('"').strip("'")
        values[key] = raw_value
    return values, text[match.end() :]


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]', " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "search"


def load_records(xlikes_root: Path) -> list[SearchRecord]:
    date_root = xlikes_root / "01 Date"
    records: list[SearchRecord] = []
    for note in date_root.rglob("*.md"):
        if note.name == "Index.md":
            continue
        frontmatter, body = parse_frontmatter(note)
        tweet_id = frontmatter.get("tweet_id", "").strip()
        if not tweet_id:
            continue
        records.append(
            SearchRecord(
                title=frontmatter.get("title") or note.stem,
                rel_path=note.relative_to(xlikes_root),
                tweet_id=tweet_id,
                author_handle=frontmatter.get("author_handle", ""),
                author_name=frontmatter.get("author_name", ""),
                created_at=frontmatter.get("created_at", ""),
                domain=frontmatter.get("domain", ""),
                source=frontmatter.get("source", ""),
                content=body,
            )
        )
    return records


def match_records(records: list[SearchRecord], query: str) -> list[SearchRecord]:
    terms = [term.lower() for term in query.split() if term.strip()]
    if not terms:
        return []
    matched: list[SearchRecord] = []
    for record in records:
        haystack = "\n".join(
            [
                record.title,
                record.author_handle,
                record.author_name,
                record.domain,
                record.source,
                record.content,
            ]
        ).lower()
        if all(term in haystack for term in terms):
            matched.append(record)
    return sorted(matched, key=lambda item: (item.created_at, item.tweet_id), reverse=True)


def unique_output_path(search_root: Path, base_name: str) -> Path:
    candidate = search_root / f"{base_name}.md"
    counter = 2
    while candidate.exists():
        candidate = search_root / f"{base_name} ({counter}).md"
        counter += 1
    return candidate


def write_search_note(xlikes_root: Path, query: str, matched: list[SearchRecord], note_title: str | None = None) -> Path:
    search_root = xlikes_root / "04 Search"
    search_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = note_title or f"{datetime.now().strftime('%Y-%m-%d')} - {query}"
    output_path = unique_output_path(search_root, sanitize_filename(title))

    lines = [
        "---",
        f'query: "{query}"',
        f'count: {len(matched)}',
        'tags: ["x-like", "search-result"]',
        "---",
        "",
        f"# {title}",
        "",
        f"- 检索词：`{query}`",
        f"- 生成时间：`{timestamp}`",
        f"- 命中数量：`{len(matched)}`",
        "",
        "## 结果",
        "",
    ]

    for record in matched:
        author = record.author_name or record.author_handle or "未知"
        lines.append(f"- [[{record.rel_path.as_posix()}|{record.title}]]")
        lines.append(f"  作者：{author} | 日期：{record.created_at} | 领域：{record.domain}")
        if record.source:
            lines.append(f"  链接：{record.source}")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search existing X Likes notes and write results into 04 Search.")
    parser.add_argument("--xlikes-root", required=True, help="Path to X Likes root")
    parser.add_argument("--query", required=True, help="Search terms")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of results to write")
    parser.add_argument("--note-title", help="Optional output note title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    xlikes_root = Path(args.xlikes_root).expanduser().resolve()
    records = load_records(xlikes_root)
    matched = match_records(records, args.query)[: args.limit]
    output_path = write_search_note(xlikes_root, args.query, matched, args.note_title)
    print(f"results={len(matched)}")
    print(f"output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
