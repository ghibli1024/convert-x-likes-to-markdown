---
name: convert-x-likes-to-markdown
description: Convert X (Twitter) likes JSON exports into a locally stored, classified Markdown archive (Obsidian-friendly but editor-agnostic), with user-controlled merge/create and auto/manual classification.
---

# X Likes Markdown Sync

## Overview

Core purpose: convert X likes JSON into local Markdown files with domain classification and indexes.
Obsidian is a primary target, but output is plain Markdown and works in other editors.

## Required User Decisions

Collect and confirm all of these before running:
1. JSON path.
2. Target root `XX` (output at `XX/X Likes/`).
3. Write mode: `merge` or `create`.
4. Classification mode: `auto` or `manual`.
5. Manual rules path if `manual`.
6. Title language: `en` or `zh` (controls generated note labels/month names/domain display names; top-level root names stay fixed).
7. Final execution confirmation.

Do not assume defaults for `merge/create` or `auto/manual`.

## Output Contract

Final structure under `XX/X Likes/` (always fixed):
- `01 Date/`
- `02 Author/`
- `03 Domain/`
- `Dashboard.md`

Title fallback rule:
- If title extraction fails (empty title), use fallback as `Post <last6>` in `en` mode or `帖子 <last6>` in `zh` mode.

## Domain Rules

1. Domain leaf categories are markdown files, not `folder + Index.md`.
2. Build hierarchy only when needed for indexing control.
3. Max hierarchy depth: `8`.
4. Top-level categories under `03 Domain` must be logically grouped and no more than `20`.
5. If any leaf file exceeds `100` posts, split further by content semantics.
6. Merge semantically equivalent labels (for example, `Agent自动化` and `Agent与自动化`).

## Classification Rules

Auto mode must use JSON evidence, including:
- `full_text`
- `metadata.legacy.entities` (hashtags, URLs, media)
- media types
- URL host signals

Auto mode is semantic classification, not a fixed one-shot mapping.

## Workflow

1. Confirm user decisions.
2. Run `scripts/sync_x_likes.py`.
3. Read JSON summary.
4. Verify output structure and constraints.
5. Report counts and key metrics.

## Commands

Auto:
```bash
python3 /Users/wukang/.codex/skills/convert-x-likes-to-markdown/scripts/sync_x_likes.py \
  --input-json "/path/to/export.json" \
  --target-root "/path/to/xx" \
  --mode merge \
  --classification auto \
  --title-language en
```

Manual:
```bash
python3 /Users/wukang/.codex/skills/convert-x-likes-to-markdown/scripts/sync_x_likes.py \
  --input-json "/path/to/export.json" \
  --target-root "/path/to/xx" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/manual-rules.json" \
  --title-language zh
```

## Validation Checklist

After running, ensure:
1. Root contains only `01 Date`, `02 Author`, `03 Domain`, `Dashboard.md`.
2. `final_tweet_notes == final_notes`.
3. `top_domain_count <= 20`.
4. `max_domain_depth <= 8`.
5. `oversized_leaf_count == 0`.
