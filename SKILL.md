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
5. Manual classification source if `manual` (either pasted into the input box or given as another Markdown note path).
6. Title language: `en` or `zh` (controls generated note labels/month names/domain display names; top-level root names stay fixed).
7. Final execution confirmation.

Do not assume defaults for `merge/create` or `auto/manual`.

When the skill is triggered, do not jump straight to conversion. First tell the user exactly which inputs are required and what the allowed options are.

Use a compact intake checklist that includes:
- `JSON path`: absolute path to the X likes export JSON.
- `target-root`: the parent directory `XX`; output will always be written to `XX/X Likes/`.
- `mode`: `merge` or `create`.
- `classification`: `auto` or `manual`.
- `auto-note`: only when `classification=auto`; do not ask the user to fill this in if a preferred Markdown classification note is already established for the workspace or conversation. Use that note automatically. Example: an already-designated note such as `文件夹目录索引.md`.
- `manual-source`: required only when `classification=manual`; otherwise allow blank. Accept either:
  - pasted Markdown classification content in the input box
  - an absolute path to another Markdown classification note
- `title-language`: `en` or `zh`.
- `confirm`: explicit execution confirmation such as `run`.

Default interaction style: ask for the required inputs in a short one-question-at-a-time flow. For each question, state the allowed options inline when relevant.

Recommended question order:
1. Confirm or collect `input-json`.
2. Confirm or collect `target-root`.
3. Ask `mode`: `merge` or `create`.
4. Ask `classification`: `auto` or `manual`.
5. If `classification=auto`, state which established Markdown classification note will be used and ask only if it is ambiguous or missing.
6. Ask `manual-source` only if `classification=manual`.
7. Ask `title-language`: `en` or `zh`.
8. Ask for final confirmation before execution.

Do not require the user to answer in a single structured line unless the user explicitly asks for a compact form. A single-line template may be offered as an optional shortcut, not as the default.

If the user provides a path ending in `/X Likes`, treat it as the intended final output folder, normalize `target-root` to its parent directory, and explicitly ask the user to confirm that normalization before running.

If the user is testing this skill and gives feedback on the workflow, wording, required inputs, or acceptable rule-source formats, treat that feedback as a request to update the skill. Modify this `SKILL.md` before continuing whenever the feedback changes future expected behavior.

If the user provides an existing archive/repository and the task is to update or merge into it, explicitly tell the user that the existing archive structure will be treated as the source of truth unless they clearly ask for a different behavior. If the user has already designated a preferred Markdown classification note for that repository, treat that note as part of the repository convention.

## Output Contract

Final structure under `XX/X Likes/` (always fixed):
- `01 Date/`
- `02 Author/`
- `03 Domain/`
- `04 Search/`
- `05 Rubbish/`
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

Auto mode in this customized workflow means: use the user's default Markdown classification note automatically. Example: if the user has already designated `文件夹目录索引.md`, use it as the auto taxonomy source.

Auto mode must still use JSON evidence, including:
- `full_text`
- `metadata.legacy.entities` (hashtags, URLs, media)
- media types
- URL host signals

In auto mode:
- if the workspace or conversation already established a preferred Markdown classification note, use that note automatically
- do not ask the user to re-provide a rule source unless that default note is missing or ambiguous
- treat that Markdown note as the taxonomy target, and use JSON evidence only to map posts into that taxonomy
- if the current repository already follows that note, preserve it; do not silently invent a parallel taxonomy

When an existing archive/repository is provided and the task is an incremental update in `merge` mode:
- inspect the existing archive first
- treat the existing repository structure as authoritative, including current language choice, domain naming, and category layout
- place new items into the existing taxonomy whenever possible instead of inventing a parallel category system
- preserve the user's current classification style even if it differs from the default examples in this skill

Priority rule:
- if the user explicitly chooses an existing repository, selects `mode=merge`, and selects `classification=auto`, use the established default Markdown classification note plus JSON evidence only to map incoming posts into that repository's current structure
- otherwise, classification should default to the user's current categories and current repository conventions, not a newly inferred taxonomy

Do not silently switch an existing archive from Chinese labels to English labels, or from one category scheme to another, just because `title-language` or `classification` was mentioned. In merge/update flows, preserve the repository's established structure unless the user clearly requests a structural rewrite.

For manual mode, a Markdown note may be used as the classification-rule source. In that case:
- ask the user to provide the source
- accept either pasted Markdown content in the input box or an absolute path to another Markdown note
- treat the Markdown note as guidance for the desired taxonomy
- parse headings, bullet hierarchies, wikilink jump lists, and repeated category labels as candidate domains
- generate or infer executable matching rules as needed before running the sync script
- the Markdown note is a rule source, not the data input; the X likes JSON remains the only content input
- if the user pasted the source inline, write it to a temporary Markdown note or parse it directly before execution; do not make the user create a file unless they asked
- when the user explicitly asks to reclassify the existing archive with the new manual rules, allow the new taxonomy to replace the previous repository structure

## Workflow

1. Present the required-input checklist and collect answers in a one-question-at-a-time flow by default.
2. Confirm user decisions.
3. If the user supplied `/X Likes` instead of `target-root`, normalize to the parent directory and confirm the interpretation.
4. If the user points to an existing archive/repository and the task is `merge`, inspect that archive before running so you understand its current language and classification structure.
5. In merge/update flows, state back that the existing repository structure will be preserved and used as the classification reference unless the user explicitly asks for a different structure.
6. If `classification=auto`, automatically use the established default Markdown classification note for the workspace or conversation; do not ask for another rule source unless needed to disambiguate.
7. If `classification=manual`, collect a Markdown source from the user, either pasted inline or via another Markdown path.
8. If the rule source is Markdown, parse or transform it into executable rules before running `scripts/sync_x_likes.py`.
9. If the user explicitly asks to reclassify both new and existing posts with the chosen rule source, honor that request and say that the old structure will be rewritten to match that source.
10. If the user is actively testing the skill and requests behavior changes, update this skill first.
11. Run `scripts/sync_x_likes.py`.
12. Read JSON summary.
13. Verify output structure and constraints.
14. Verify `01 Date` uses only four-digit year folders and Chinese numeric month folders such as `3 月`; no duplicate year folders like `2025 2` or English month folders such as `Mar`.
15. Preserve `04 Search/` as the dedicated location for future search/query result notes. If it does not exist yet, create it.
16. Preserve `05 Rubbish/` as the dedicated location for posts the user wants removed from the archive. If it does not exist yet, create it.
17. Before writing final views, read `05 Rubbish/` and remove any referenced posts from the merged archive records.
18. Report counts and key metrics.

## Commands

Auto:
```bash
python3 /Users/Totoro/.codex/skills/convert-x-likes-to-markdown/scripts/sync_x_likes.py \
  --input-json "/path/to/export.json" \
  --target-root "/path/to/xx" \
  --mode merge \
  --classification manual \
  --manual-rules "/path/to/default-classification-note.md" \
  --title-language en
```

Manual:
```bash
python3 /Users/Totoro/.codex/skills/convert-x-likes-to-markdown/scripts/sync_x_likes.py \
  --input-json "/path/to/export.json" \
  --target-root "/path/to/xx" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/user-provided-classification-note.md" \
  --title-language zh
```

## Validation Checklist

After running, ensure:
1. Root contains `01 Date`, `02 Author`, `03 Domain`, `04 Search`, `05 Rubbish`, `Dashboard.md`.
2. `final_tweet_notes == final_notes`.
3. `top_domain_count <= 20`.
4. `max_domain_depth <= 8`.
5. `oversized_leaf_count == 0`.
6. `01 Date` has no duplicate year folders and no English month folders.
7. Any posts referenced from `05 Rubbish/` are removed from the generated archive views.
