from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse


WEAK_CATEGORY_SUFFIXES = (
    "相关",
    "类别",
    "分类",
    "类",
    "工具",
    "网站",
    "资源",
    "平台",
    "推荐",
    "导航",
    "大全",
    "合集",
    "汇总",
)

TOKEN_SYNONYMS: Dict[str, Set[str]] = {
    "图像": {"图片", "照片", "img", "image", "photo"},
    "生成": {"生图", "绘图", "画图", "作图"},
    "对话": {"聊天", "chat", "chatbot"},
    "智能体": {"agent", "agents", "代理"},
    "聚合": {"集成", "合集", "一站式"},
    "部署": {"本地部署", "自托管", "搭建", "运行"},
    "写作": {"写文", "写文章", "文案", "写稿"},
    "搜索": {"检索", "搜", "find"},
    "导航": {"入口", "聚合"},
}


@dataclass
class TaxonomyReference:
    source_path: Path
    source_format: str
    root_label: str
    macro_groups: List[str]
    primary_categories_by_macro: Dict[str, List[str]]
    primary_categories: List[str]
    normalized_categories: Dict[str, str]
    reference_paths: List[Tuple[str, ...]]
    children_by_parent: Dict[Tuple[str, ...], List[str]]
    normalized_children_by_parent: Dict[Tuple[str, ...], Dict[str, str]]
    aliases_by_path: Dict[Tuple[str, ...], List[str]]
    scope_by_path: Dict[Tuple[str, ...], str]
    own_tokens_by_path: Dict[Tuple[str, ...], Set[str]]
    subtree_tokens_by_path: Dict[Tuple[str, ...], Set[str]]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def unwrap_markdown_label(value: str) -> str:
    text = clean_text(value)
    if text.startswith("[[") and text.endswith("]]"):
        inner = text[2:-2].strip()
        if "|" in inner:
            inner = inner.split("|", 1)[1].strip()
        elif "#" in inner:
            inner = inner.split("#", 1)[1].strip()
        return clean_text(inner)
    return text


def split_taxonomy_label(raw_value: str) -> Tuple[str, str]:
    text = clean_text(unwrap_markdown_label(raw_value))
    descriptor = ""
    trailing = re.match(r"^(.*?)[\(\[（【]([^)\]）】]+)[\)\]）】]\s*$", text)
    if trailing:
        text = clean_text(trailing.group(1))
        descriptor = clean_text(trailing.group(2))
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text)
    text = re.sub(r"^📂\s*", "", text)
    return clean_text(text), descriptor


def normalize_category_label(value: str) -> str:
    text = clean_text(unwrap_markdown_label(value))
    if not text:
        return ""
    text = re.sub(r"[\(\[（【][^\)\]）】]*[\)\]）】]", " ", text)
    chars: List[str] = []
    for ch in text:
        if ch in {"_", "-", "/", "|", "、", "，", ",", "：", ":", "·"}:
            chars.append(" ")
            continue
        category = unicodedata.category(ch)
        if category.startswith("S") or category.startswith("P"):
            chars.append(" ")
            continue
        chars.append(ch)
    text = clean_text("".join(chars).lower())
    text = re.sub(r"\s+", " ", text)
    for connector in ("与", "和", "及"):
        text = text.replace(connector, " ")
    text = clean_text(text)
    changed = True
    while changed and text:
        changed = False
        for suffix in WEAK_CATEGORY_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = clean_text(text[: -len(suffix)])
                changed = True
    return text


def category_label_tokens(value: str) -> Set[str]:
    normalized = normalize_category_label(value)
    if not normalized:
        return set()
    tokens: Set[str] = set()
    for piece in re.split(r"\s+", normalized):
        if not piece:
            continue
        tokens.add(piece)
        if re.search(r"[\u4e00-\u9fff]", piece):
            if len(piece) >= 2:
                for idx in range(len(piece) - 1):
                    tokens.add(piece[idx : idx + 2])
        else:
            for subpiece in re.split(r"[^a-z0-9]+", piece):
                if subpiece:
                    tokens.add(subpiece)
    return tokens


def expand_semantic_tokens(tokens: Set[str]) -> Set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(TOKEN_SYNONYMS.get(token, set()))
    return expanded


def semantic_tokens_for_text(value: str) -> Set[str]:
    return expand_semantic_tokens(category_label_tokens(value))


def semantic_tokens_for_record(record: Dict[str, object]) -> Set[str]:
    tokens: Set[str] = set()
    tokens.update(semantic_tokens_for_text(str(record.get("title", ""))))
    tokens.update(semantic_tokens_for_text(str(record.get("content", ""))))
    host = str(record.get("host", ""))
    if host:
        host_parts = [part for part in re.split(r"[.\-_]+", host) if part]
        tokens.update(semantic_tokens_for_text(" ".join(host_parts)))
    url = str(record.get("url", ""))
    parsed = urlparse(url)
    path_parts = [part for part in re.split(r"[\/._\-]+", parsed.path) if part]
    if path_parts:
        tokens.update(semantic_tokens_for_text(" ".join(path_parts)))
    query_parts = [part for part in re.split(r"[=&._\-]+", parsed.query) if part]
    if query_parts:
        tokens.update(semantic_tokens_for_text(" ".join(query_parts[:12])))
    return tokens


def dedupe_strings(values: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def dedupe_paths(values: Sequence[Sequence[str]]) -> List[List[str]]:
    seen: Set[Tuple[str, ...]] = set()
    out: List[List[str]] = []
    for parts in values:
        key = tuple(parts)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(parts))
    return sorted(out, key=lambda item: (len(item), [part.lower() for part in item]))


def normalized_source_parts(paths: Sequence[Sequence[str]]) -> Set[str]:
    values: Set[str] = set()
    for path in paths:
        for part in path:
            normalized = normalize_category_label(str(part))
            if normalized:
                values.add(normalized)
    return values


def parse_overview_groups(lines: Sequence[str]) -> List[Tuple[str, List[str]]]:
    in_overview = False
    groups: List[Tuple[str, List[str]]] = []
    current_group = ""
    current_items: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not in_overview:
            if stripped == "## 一级主类速览":
                in_overview = True
            continue
        if stripped.startswith("## ") and stripped != "## 一级主类速览":
            break
        heading = re.match(r"^###\s+(.+?)\s*$", stripped)
        if heading:
            if current_group:
                groups.append((current_group, current_items))
            current_group = clean_text(heading.group(1))
            current_items = []
            continue
        bullet = re.match(r"^-\s+(.+?)\s*$", stripped)
        if bullet and current_group:
            label = unwrap_markdown_label(bullet.group(1))
            if label:
                current_items.append(label)

    if current_group:
        groups.append((current_group, current_items))
    return [(group, dedupe_strings(items)) for group, items in groups if group]


def build_taxonomy_children(
    reference_paths: Sequence[Tuple[str, ...]],
    aliases_by_path: Optional[Dict[Tuple[str, ...], List[str]]] = None,
) -> Tuple[Dict[Tuple[str, ...], List[str]], Dict[Tuple[str, ...], Dict[str, str]]]:
    children: DefaultDict[Tuple[str, ...], Set[str]] = defaultdict(set)
    for path in reference_paths:
        for depth in range(len(path) - 1):
            parent = tuple(path[: depth + 1])
            children[parent].add(path[depth + 1])
    children_by_parent = {parent: sorted(values, key=str.lower) for parent, values in children.items()}
    normalized_children_by_parent: Dict[Tuple[str, ...], Dict[str, str]] = {}
    for parent, child_names in children_by_parent.items():
        normalized_map: Dict[str, str] = {}
        for child in child_names:
            normalized = normalize_category_label(child)
            if normalized and normalized not in normalized_map:
                normalized_map[normalized] = child
            child_path = parent + (child,)
            for alias in (aliases_by_path or {}).get(child_path, []):
                normalized_alias = normalize_category_label(alias)
                if normalized_alias and normalized_alias not in normalized_map:
                    normalized_map[normalized_alias] = child
        normalized_children_by_parent[parent] = normalized_map
    return children_by_parent, normalized_children_by_parent


def build_taxonomy_token_maps(
    reference_paths: Sequence[Tuple[str, ...]],
    aliases_by_path: Dict[Tuple[str, ...], List[str]],
    scope_by_path: Dict[Tuple[str, ...], str],
) -> Tuple[Dict[Tuple[str, ...], Set[str]], Dict[Tuple[str, ...], Set[str]]]:
    own_tokens_by_path: Dict[Tuple[str, ...], Set[str]] = {}
    subtree_tokens_by_path: Dict[Tuple[str, ...], Set[str]] = {}

    for path in reference_paths:
        own_tokens: Set[str] = set()
        if path:
            own_tokens.update(semantic_tokens_for_text(path[-1]))
        for alias in aliases_by_path.get(path, []):
            own_tokens.update(semantic_tokens_for_text(alias))
        scope = scope_by_path.get(path, "")
        if scope:
            own_tokens.update(semantic_tokens_for_text(scope))
        own_tokens_by_path[path] = own_tokens

    for path in sorted(reference_paths, key=len, reverse=True):
        subtree = set(own_tokens_by_path.get(path, set()))
        for other in reference_paths:
            if len(other) > len(path) and other[: len(path)] == path:
                subtree.update(own_tokens_by_path.get(other, set()))
        subtree_tokens_by_path[path] = subtree
    return own_tokens_by_path, subtree_tokens_by_path


def count_paths_under_prefix(reference_paths: Sequence[Tuple[str, ...]], prefix: Tuple[str, ...]) -> int:
    return sum(1 for path in reference_paths if len(path) >= len(prefix) and path[: len(prefix)] == prefix)


def count_descendants(children_by_parent: Dict[Tuple[str, ...], List[str]], prefix: Tuple[str, ...]) -> int:
    count = 0
    stack = [prefix]
    while stack:
        current = stack.pop()
        children = children_by_parent.get(current, [])
        count += len(children)
        for child in children:
            stack.append(current + (child,))
    return count


def render_ai_outline_sync_sections(reference: TaxonomyReference) -> str:
    def render_path_lines() -> List[str]:
        path_lines = ["", "## 4. 规范路径清单", ""]
        for idx, ref_path in enumerate(reference.reference_paths, 1):
            path_lines.append(f"4.{idx} PATH = {' / '.join(ref_path)}")
        return path_lines

    def render_descendants(lines: List[str], parent_path: Tuple[str, ...], number: str, primary_child_length: int) -> None:
        for child_idx, child in enumerate(reference.children_by_parent.get(parent_path, []), 1):
            child_path = parent_path + (child,)
            child_number = f"{number}.{child_idx}"
            node_type = "primary_category" if len(child_path) == primary_child_length else "category"
            attrs = [f"type={node_type}", f"child_count={len(reference.children_by_parent.get(child_path, []))}"]
            if node_type == "primary_category":
                aliases = reference.aliases_by_path.get(child_path, [])
                attrs.insert(1, f"alias={aliases[0] if aliases else '-'}")
            scope = clean_text(reference.scope_by_path.get(child_path, ""))
            if scope:
                attrs.append(f"scope={scope}")
            lines.append(f"{child_number} {child} | " + " | ".join(attrs))
            render_descendants(lines, child_path, child_number, primary_child_length)

    if not reference.macro_groups:
        outline_lines = ["## 3. 规范大纲树", "", f"3.0 {reference.root_label} | type=root | note=唯一根节点"]
        render_descendants(outline_lines, (reference.root_label,), "3", 2)
        return "\n".join(outline_lines + render_path_lines()).rstrip() + "\n"

    group_lines = ["## 一级分组索引", ""]
    for idx, group in enumerate(reference.macro_groups, 1):
        group_path = (reference.root_label, group)
        primary = reference.primary_categories_by_macro.get(group, [])
        path_count = count_paths_under_prefix(reference.reference_paths, group_path) - 1
        node_count = count_descendants(reference.children_by_parent, group_path)
        scope = clean_text(reference.scope_by_path.get(group_path, "")) or "未说明"
        group_lines.append(
            f"2.{idx} {group} | category_count={len(primary)} | path_count={max(path_count, 0)} | node_count={node_count} | scope={scope}"
        )

    outline_lines = ["", "## 机器大纲", "", "下面的 `3.x` 是脚本真正读取的核心结构。", "你可以编辑上面的分组与主类速览；下一次运行时，这一段会自动同步。", "", "3.0 ROOT | type=root | note=唯一根节点"]
    for idx, group in enumerate(reference.macro_groups, 1):
        outline_lines.extend(["", f"### {group}", ""])
        group_path = (reference.root_label, group)
        group_scope = clean_text(reference.scope_by_path.get(group_path, ""))
        attrs = [f"type=macro_group", f"child_count={len(reference.children_by_parent.get(group_path, []))}"]
        if group_scope:
            attrs.append(f"scope={group_scope}")
        outline_lines.append(f"3.{idx} {group} | " + " | ".join(attrs))
        render_descendants(outline_lines, group_path, f"3.{idx}", 3)

    ungrouped_root_children = [child for child in reference.children_by_parent.get((reference.root_label,), []) if child not in set(reference.macro_groups)]
    for offset, child in enumerate(ungrouped_root_children, len(reference.macro_groups) + 1):
        child_path = (reference.root_label, child)
        aliases = reference.aliases_by_path.get(child_path, [])
        attrs = [f"type=primary_category", f"alias={aliases[0] if aliases else '-'}", f"child_count={len(reference.children_by_parent.get(child_path, []))}"]
        scope = clean_text(reference.scope_by_path.get(child_path, ""))
        if scope:
            attrs.append(f"scope={scope}")
        outline_lines.append(f"3.{offset} {child} | " + " | ".join(attrs))
        render_descendants(outline_lines, child_path, f"3.{offset}", 2)

    return "\n".join(group_lines + outline_lines + render_path_lines()).rstrip() + "\n"


def parse_ai_outline_reference(lines: Sequence[str], path: Path) -> TaxonomyReference:
    nodes: List[Tuple[str, str, Dict[str, str]]] = []
    for line in lines:
        match = re.match(r"^(3(?:\.\d+)*)\s+(.+?)(?:\s+\|\s+(.+))?$", line.strip())
        if not match:
            continue
        number, raw_label, meta = match.groups()
        attrs: Dict[str, str] = {}
        if meta:
            for part in meta.split(" | "):
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                attrs[key] = value
        nodes.append((number, raw_label, attrs))
    if not nodes:
        raise ValueError(f"failed to parse AI outline taxonomy from: {path}")

    root_label = ""
    primary_categories: List[str] = []
    overview_groups = parse_overview_groups(lines)
    display_path_by_number: Dict[str, Tuple[str, ...]] = {}
    aliases_by_path: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    scope_by_path: Dict[Tuple[str, ...], str] = {}
    reference_paths: List[Tuple[str, ...]] = []
    seen_paths: Set[Tuple[str, ...]] = set()
    primary_numbers: Dict[str, str] = {}
    primary_aliases_by_number: Dict[str, List[str]] = defaultdict(list)
    primary_to_machine_macro: Dict[str, str] = {}
    primary_to_machine_macro_number: Dict[str, str] = {}
    macro_label_by_number: Dict[str, str] = {}

    for number, raw_label, attrs in nodes:
        label, _ = split_taxonomy_label(raw_label)
        node_type = attrs.get("type", "")
        if node_type == "macro_group":
            macro_label_by_number[number] = label
        if node_type == "primary_category":
            primary_numbers[number] = label
            alias = clean_text(attrs.get("alias", ""))
            if alias and alias != "-":
                primary_aliases_by_number[number].append(alias)
            parent_number = ".".join(number.split(".")[:-1])
            primary_to_machine_macro[number] = macro_label_by_number.get(parent_number, "")
            primary_to_machine_macro_number[number] = parent_number

    primary_lookup: Dict[str, str] = {}
    for number, label in primary_numbers.items():
        for candidate in [label, *primary_aliases_by_number.get(number, [])]:
            normalized = normalize_category_label(candidate)
            if normalized and normalized not in primary_lookup:
                primary_lookup[normalized] = number

    macro_groups: List[str] = []
    primary_categories_by_macro: Dict[str, List[str]] = defaultdict(list)
    primary_to_macro_label: Dict[str, str] = {}
    assigned_primary_numbers: Set[str] = set()
    ordered_macro_numbers = sorted(macro_label_by_number, key=lambda item: [int(part) for part in item.split(".")])
    overview_macro_label_by_number: Dict[str, str] = {}
    if overview_groups:
        for idx, number in enumerate(ordered_macro_numbers):
            if idx < len(overview_groups):
                overview_macro_label_by_number[number] = overview_groups[idx][0]

    for group_name, items in overview_groups:
        if group_name not in macro_groups:
            macro_groups.append(group_name)
        for item in items:
            normalized = normalize_category_label(item)
            primary_number = primary_lookup.get(normalized, "")
            if primary_number:
                assigned_primary_numbers.add(primary_number)
                primary_to_macro_label[primary_number] = group_name
                canonical_label = primary_numbers[primary_number]
                if canonical_label not in primary_categories_by_macro[group_name]:
                    primary_categories_by_macro[group_name].append(canonical_label)

    for number, label in primary_numbers.items():
        if number in assigned_primary_numbers:
            continue
        group_label = primary_to_machine_macro.get(number) or ""
        if group_label:
            if group_label not in macro_groups:
                macro_groups.append(group_label)
            primary_to_macro_label[number] = group_label
            if label not in primary_categories_by_macro[group_label]:
                primary_categories_by_macro[group_label].append(label)

    machine_macro_to_overview: Dict[str, str] = {}
    for primary_number, macro_number in primary_to_machine_macro_number.items():
        overview_label = primary_to_macro_label.get(primary_number, "")
        if macro_number and overview_label and macro_number not in machine_macro_to_overview:
            machine_macro_to_overview[macro_number] = overview_label

    for number, raw_label, attrs in nodes:
        label, descriptor = split_taxonomy_label(raw_label)
        node_type = attrs.get("type", "")
        parent_number = ".".join(number.split(".")[:-1])
        parent_display = display_path_by_number.get(parent_number, tuple())

        if node_type == "root":
            root_label = label or "ROOT"
            display_path = (root_label,)
        elif node_type == "macro_group":
            macro_label = machine_macro_to_overview.get(number) or overview_macro_label_by_number.get(number) or label or primary_to_machine_macro.get(number, "")
            if not macro_label:
                display_path = parent_display or (root_label,)
            else:
                display_path = (root_label, macro_label)
                if display_path not in seen_paths:
                    seen_paths.add(display_path)
                    reference_paths.append(display_path)
        else:
            if node_type == "primary_category":
                macro_label = primary_to_macro_label.get(number, "")
                parent_display = (root_label, macro_label) if macro_label else (root_label,)
            elif not parent_display:
                parent_display = (root_label,)
            display_path = parent_display + ((label,) if label else tuple())
            if display_path and display_path not in seen_paths:
                seen_paths.add(display_path)
                reference_paths.append(display_path)

        display_path_by_number[number] = display_path
        if not display_path:
            continue
        alias = clean_text(attrs.get("alias", ""))
        if alias and alias != "-":
            aliases_by_path[display_path].append(alias)
        scope_parts = [clean_text(attrs.get("scope", ""))]
        if descriptor:
            scope_parts.append(descriptor)
        scope_text = clean_text(" ".join(part for part in scope_parts if part))
        if scope_text:
            scope_by_path[display_path] = scope_text
        if node_type == "primary_category" and len(display_path) >= 2:
            category = display_path[-1]
            if category not in primary_categories:
                primary_categories.append(category)

    normalized_categories: Dict[str, str] = {}
    for category in primary_categories:
        normalized = normalize_category_label(category)
        if normalized and normalized not in normalized_categories:
            normalized_categories[normalized] = category
    primary_category_set = set(primary_categories)
    for ref_path, aliases in aliases_by_path.items():
        if ref_path and ref_path[-1] in primary_category_set:
            for alias in aliases:
                normalized_alias = normalize_category_label(alias)
                if normalized_alias and normalized_alias not in normalized_categories:
                    normalized_categories[normalized_alias] = ref_path[-1]

    children_by_parent, normalized_children_by_parent = build_taxonomy_children(reference_paths, dict(aliases_by_path))
    own_tokens_by_path, subtree_tokens_by_path = build_taxonomy_token_maps(reference_paths, dict(aliases_by_path), scope_by_path)
    return TaxonomyReference(
        source_path=path,
        source_format="ai_outline_v1",
        root_label=root_label or "ROOT",
        macro_groups=macro_groups,
        primary_categories_by_macro={key: value for key, value in primary_categories_by_macro.items()},
        primary_categories=primary_categories,
        normalized_categories=normalized_categories,
        reference_paths=sorted(reference_paths, key=lambda item: (len(item), [part.lower() for part in item])),
        children_by_parent=children_by_parent,
        normalized_children_by_parent=normalized_children_by_parent,
        aliases_by_path={key: dedupe_strings(value) for key, value in aliases_by_path.items()},
        scope_by_path=scope_by_path,
        own_tokens_by_path=own_tokens_by_path,
        subtree_tokens_by_path=subtree_tokens_by_path,
    )


def parse_taxonomy_reference_markdown(path: Path) -> TaxonomyReference:
    lines = path.read_text(encoding="utf-8").splitlines()
    if any(line.strip() == "FORMAT: AI_OUTLINE_V1" for line in lines[:20]):
        return parse_ai_outline_reference(lines, path)
    raise ValueError(f"unsupported taxonomy markdown format: {path}")


def primary_category_display_path(reference: TaxonomyReference, primary_label: str) -> List[str]:
    for macro_group, primary_labels in reference.primary_categories_by_macro.items():
        if primary_label in primary_labels:
            return [reference.root_label, macro_group, primary_label]
    return [reference.root_label, primary_label]


def resolve_reference_category(source_main: str, reference: TaxonomyReference) -> str:
    clean_source = clean_text(source_main)
    if clean_source in reference.primary_categories:
        return clean_source
    normalized_source = normalize_category_label(clean_source)
    if normalized_source and normalized_source in reference.normalized_categories:
        return reference.normalized_categories[normalized_source]

    source_tokens = category_label_tokens(clean_source)
    best_target = reference.primary_categories[0]
    best_score: Tuple[int, int, float] = (-1, -1, -1.0)
    for target in reference.primary_categories:
        normalized_target = normalize_category_label(target)
        target_tokens = category_label_tokens(target)
        overlap = len(source_tokens & target_tokens)
        containment = 1 if normalized_source and normalized_target and (
            normalized_source in normalized_target or normalized_target in normalized_source
        ) else 0
        ratio = SequenceMatcher(None, normalized_source or clean_source, normalized_target or target.lower()).ratio()
        score = (overlap, containment, ratio)
        if score > best_score:
            best_target = target
            best_score = score
    return best_target


def semantic_match_score(
    candidate_path: Tuple[str, ...],
    feature_tokens: Set[str],
    source_norm_parts: Set[str],
    reference: TaxonomyReference,
) -> int:
    own_tokens = reference.own_tokens_by_path.get(candidate_path, set())
    subtree_tokens = reference.subtree_tokens_by_path.get(candidate_path, own_tokens)
    score = 0
    score += 6 * len(feature_tokens & own_tokens)
    score += 2 * len(feature_tokens & subtree_tokens)
    candidate_norm = normalize_category_label(candidate_path[-1]) if candidate_path else ""
    if candidate_norm and candidate_norm in source_norm_parts:
        score += 8
    for alias in reference.aliases_by_path.get(candidate_path, []):
        normalized_alias = normalize_category_label(alias)
        if normalized_alias and normalized_alias in source_norm_parts:
            score += 8
    return score


def classify_record_semantically(
    record: Dict[str, object],
    reference: TaxonomyReference,
) -> Tuple[List[str], str]:
    raw_source_paths = record.get("source_category_paths", record.get("category_paths", [[]]))
    if not isinstance(raw_source_paths, list) or not raw_source_paths:
        raw_source_paths = [[]]
    normalized_paths = dedupe_paths([[reference.root_label, *parts] for parts in raw_source_paths])
    source_norm_parts = normalized_source_parts(normalized_paths)
    feature_tokens = semantic_tokens_for_record(record)

    root = (reference.root_label,)
    current = root
    chosen_path = [reference.root_label]
    overall_mode = "semantic"

    while True:
        children = reference.children_by_parent.get(current, [])
        if not children:
            break
        scored: List[Tuple[int, str]] = []
        exact_match_child = ""
        normalized_match_child = ""
        normalized_child_map = reference.normalized_children_by_parent.get(current, {})
        for source_norm in source_norm_parts:
            target = normalized_child_map.get(source_norm, "")
            if target:
                normalized_match_child = target
                break
        for child in children:
            child_path = current + (child,)
            score = semantic_match_score(child_path, feature_tokens, source_norm_parts, reference)
            scored.append((score, child))
            normalized_child = normalize_category_label(child)
            if normalized_child and normalized_child in source_norm_parts:
                exact_match_child = child
        scored.sort(key=lambda item: (-item[0], item[1].lower()))
        if not scored:
            break
        if exact_match_child:
            best_child = exact_match_child
            best_score = next((score for score, child in scored if child == best_child), 0)
            if overall_mode == "semantic":
                overall_mode = "source-exact"
        elif normalized_match_child:
            best_child = normalized_match_child
            best_score = next((score for score, child in scored if child == best_child), 0)
            if overall_mode == "semantic":
                overall_mode = "source-normalized"
        else:
            best_score, best_child = scored[0]

        second_score = scored[1][0] if len(scored) > 1 else -1
        if best_score <= 0:
            break
        if best_score < 4 and second_score >= best_score:
            break
        chosen_path.append(best_child)
        current = tuple(chosen_path)

    if len(chosen_path) == 1:
        fallback_target = resolve_reference_category(
            str(record.get("title", "")) or str(record.get("host", "")),
            reference,
        )
        chosen_path = primary_category_display_path(reference, fallback_target)
        overall_mode = "fallback"
    return chosen_path, overall_mode
