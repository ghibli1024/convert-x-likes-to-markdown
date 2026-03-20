# convert-x-likes-to-markdown

[![README-English](https://img.shields.io/badge/README-English-2d6cdf?style=for-the-badge)](README.md)
[![README-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87](https://img.shields.io/badge/README-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-555555?style=for-the-badge)](README.zh-CN.md)

Convert an exported X (Twitter) Likes JSON file into a local Markdown archive.

This repository contains both:

- a Codex skill definition (`SKILL.md`)
- a standalone sync script (`scripts/sync_x_likes.py`)

The output is plain Markdown, but the structure is optimized for Obsidian-style browsing:

- date-based views
- author-based views
- domain/topic-based views
- a dashboard for summary stats

## What It Does

Given an exported X Likes JSON file, the tool can:

- parse liked posts into normalized records
- write each post as a Markdown note
- organize notes by date, author, and semantic domain
- rebuild an archive from scratch (`create`)
- merge new likes into an existing archive (`merge`)
- classify content automatically from JSON signals (`auto`)
- apply user-authored JSON or Markdown classification sources (`manual`)
- in the Codex skill workflow, reuse an established Markdown taxonomy note automatically when the user selects `auto`
- generate either English or Chinese titles for generated notes and indexes

## Repository Layout

```text
convert-x-likes-to-markdown/
├── README.md
├── SKILL.md
├── .gitignore
├── agents/
│   └── openai.yaml
├── references/
│   ├── domain-policy.md
│   └── manual-rules.example.json
└── scripts/
    └── sync_x_likes.py
```

## Requirements

- Python 3
- an exported X Likes JSON file

No external Python dependencies are required.

## How To Get The Input JSON

This project expects you to bring your own exported JSON file first.

The recommended upstream exporter is:

- [prinsss/twitter-web-exporter](https://github.com/prinsss/twitter-web-exporter)

Recommended flow:

1. Install a userscript manager such as Tampermonkey or Violentmonkey.
2. Install the `twitter-web-exporter` userscript.
3. Open the relevant page on the X/Twitter web app, for example a Likes page.
4. Scroll until the data you want is fully loaded in the browser.
5. Use the exporter panel to export the captured data as `JSON`.
6. Feed that exported JSON file into this repository's `sync_x_likes.py`.

Important notes:

- this repo does not scrape X directly
- this repo starts from an already exported JSON file
- completeness depends on what the Twitter web app has already loaded in your browser

## Input

The script expects an exported X Likes JSON file.

Example:

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto
```

## Output Structure

The output is always written under:

```text
<target-root>/<container-name>/
```

Default `container-name`:

```text
X Likes
```

Generated structure:

```text
X Likes/
├── 01 Date/
├── 02 Author/
├── 03 Domain/
├── 04 Search/
├── 05 Rubbish/
└── Dashboard.md
```

### Meaning of Each Top-Level Path

- `01 Date/`
  Browse notes by year and month.
- `02 Author/`
  Browse notes by author handle/name.
- `03 Domain/`
  Browse notes by semantic domain/topic hierarchy.
- `04 Search/`
  Store query/search result notes generated when you ask the skill to retrieve posts by topic.
- `05 Rubbish/`
  Store notes that reference posts you no longer want to keep in the X Likes archive. Any referenced posts will be removed from generated views the next time the sync skill runs.
- `Dashboard.md`
  Summary page with counts, top domains, month stats, and quick navigation.

## Search Result Convention

When this skill is used to search an existing `X Likes` archive for a topic, theme, or cluster of posts,
the default action is to write the result note into:

```text
X Likes/04 Search/
```

Recommended helper command:

```bash
python3 scripts/search_x_likes.py \
  --xlikes-root "/path/to/X Likes" \
  --query "telegram cli" \
  --note-title "Telegram CLI 检索"
```

## Rubbish Convention

If you want to remove posts from the archive, add a Markdown note under:

```text
X Likes/05 Rubbish/
```

The cleanup logic can read these references:

- wikilinks to notes under `01 Date/...`
- raw `twitter.com/.../status/<id>` or `x.com/.../status/<id>` URLs
- frontmatter `tweet_id`

When the sync skill runs again, any referenced tweet IDs are removed from the generated `01 Date`, `02 Author`, `03 Domain`, and `Dashboard` views.

## Modes

### `create`

Rebuild the archive only from the provided JSON input.

Use this when you want a clean regeneration and do not want to preserve old archive content.

### `merge`

Read existing Markdown notes, parse them back into records, and merge incoming likes into the existing archive.

Use this when you want incremental updates.

## Classification Modes

### `auto`

Auto mode uses JSON evidence from the exported likes file, including:

- post text
- URL host signals
- hashtags and entities
- media signals

It performs semantic classification and also normalizes similar categories.

Reference policy:

- [references/domain-policy.md](references/domain-policy.md)

### `manual`

Manual mode accepts a classification source that you provide.

Supported manual sources:

- a JSON rules file
- a Markdown classification note that should be parsed into executable rules

Reference example:

- [references/manual-rules.example.json](references/manual-rules.example.json)

Example:

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/classification-note.md" \
  --title-language zh
```

## Codex Skill Semantics

When this repository is used through its Codex skill, the interaction rules are slightly higher-level than the raw CLI flags:

- the skill should first show the required inputs and allowed options
- the default collection style is a short one-question-at-a-time flow
- if the user selects `auto`, the skill should automatically use the already-designated Markdown classification note for that workspace or repository when one exists
- if the user selects `manual`, the skill should ask the user to provide a Markdown classification source, either pasted inline or by giving another Markdown path
- in merge flows, the skill should inspect the existing archive first and preserve repository conventions unless the user explicitly asks for a full reclassification

In other words:

- CLI `--classification auto` still means JSON-signal auto classification
- skill-level `auto` means “use the default Markdown taxonomy note automatically, if one has already been established”

## Command Reference

### Auto classification

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto \
  --title-language en
```

### Manual classification

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/classification-note.md" \
  --title-language zh
```

### Arguments

- `--input-json`
  Path to exported X Likes JSON.
- `--target-root`
  Root directory where the archive container will be created.
- `--container-name`
  Archive folder name inside `target-root`. Defaults to `X Likes`.
- `--mode`
  Required. One of: `merge`, `create`.
- `--classification`
  Required. One of: `auto`, `manual`.
- `--title-language`
  Optional. `en` or `zh`. Defaults to `en`.
- `--manual-rules`
  Required when `--classification manual`. Accepts either a JSON rules file or a Markdown classification note.

## Generated Note Rules

- The top-level root names remain fixed: `01 Date`, `02 Author`, `03 Domain`, `Dashboard.md`
- If title extraction fails:
  - English fallback: `Post <last6>`
  - Chinese fallback: `帖子 <last6>`
- Domain leaves are Markdown files, not `folder + Index.md`
- Domain hierarchy is capped to prevent over-deep trees

## Validation Guarantees

The script validates key constraints after writing:

- root contains only `01 Date`, `02 Author`, `03 Domain`, `Dashboard.md`
- `final_tweet_notes == final_notes`
- top-level domain count stays within the configured limit
- max domain depth stays within the configured limit
- oversized domain leaves are rebalanced

Current limits from the script:

- max top-level domains: `20`
- max domain depth: `8`
- max domain leaf size before rebalance: `100`

## Example Manual Classification Sources

See:

- [references/manual-rules.example.json](references/manual-rules.example.json)

That JSON example demonstrates:

- fallback domain/tag
- keyword-based manual domain routing
- topic tag extraction

You can also use a Markdown classification note instead of JSON when your taxonomy already exists as a note hierarchy.

## Using It As a Codex Skill

This repo also ships a Codex skill definition:

- [SKILL.md](SKILL.md)

The intended interaction flow is:

1. Ask the user for the JSON path.
2. Ask where the archive should be written.
3. Ask whether to use `merge` or `create`.
4. Ask whether classification should be `auto` or `manual`.
5. If `auto`, state which established Markdown classification note will be used, and only ask if that default is missing or ambiguous.
6. If `manual`, ask for the classification source as pasted Markdown or another Markdown path.
7. Ask whether generated titles should use `en` or `zh`.
8. Run the sync command and inspect the JSON summary.

The agent config used for skill registration is:

- [agents/openai.yaml](agents/openai.yaml)

## Typical Workflow

### First run

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification auto \
  --title-language en
```

### Later incremental update

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/new-likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto \
  --title-language en
```

### Manual curation workflow

1. Start from either `manual-rules.example.json` or an existing Markdown taxonomy note
2. adapt the source to your own domain taxonomy
3. run the script in `manual` mode
4. inspect `03 Domain/` and `Dashboard.md`
5. refine the source and rerun if needed

## Notes

- The archive is editor-agnostic Markdown. Obsidian is a target, not a hard dependency.
- Auto mode is best when you want broad semantic grouping with minimal setup.
- Manual mode is best when you already know your preferred taxonomy, especially if it already exists as a Markdown note.

## License / Reuse

This project is licensed under the MIT License.

See:

- [LICENSE](LICENSE)
