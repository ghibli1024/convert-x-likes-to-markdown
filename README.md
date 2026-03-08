# convert-x-likes-to-markdown

Convert an exported X (Twitter) Likes JSON file into a local Markdown archive.

## 中文简介

这是一个把 X（Twitter）点赞导出 JSON 转成 Markdown 归档的小工具，同时也附带一份可直接给 Codex 使用的 skill 定义。

它适合用来把点赞内容沉淀成可本地保存、可检索、可分类浏览的知识库，尤其适合 Obsidian 这类 Markdown 工作流。

核心能力：

- 把点赞 JSON 转成一条条 Markdown 笔记
- 按日期、作者、主题领域生成索引
- 支持 `create` 全量重建和 `merge` 增量更新
- 支持 `auto` 自动分类和 `manual` 手工规则分类
- 支持中英文标题输出

如果你只想快速开始，可以直接看下面的 “Command Reference”。

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
- apply user-authored rules (`manual`)
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
└── Dashboard.md
```

### Meaning of Each Top-Level Path

- `01 Date/`
  Browse notes by year and month.
- `02 Author/`
  Browse notes by author handle/name.
- `03 Domain/`
  Browse notes by semantic domain/topic hierarchy.
- `Dashboard.md`
  Summary page with counts, top domains, month stats, and quick navigation.

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

Manual mode applies a first-match rules file that you provide.

Reference example:

- [references/manual-rules.example.json](references/manual-rules.example.json)

Example:

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/manual-rules.json" \
  --title-language zh
```

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
  --manual-rules "/path/to/manual-rules.json" \
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
  Required when `--classification manual`.

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

## Example Manual Rules File

See:

- [references/manual-rules.example.json](references/manual-rules.example.json)

That example demonstrates:

- fallback domain/tag
- keyword-based manual domain routing
- topic tag extraction

## Using It As a Codex Skill

This repo also ships a Codex skill definition:

- [SKILL.md](SKILL.md)

The intended interaction flow is:

1. Ask the user for the JSON path.
2. Ask where the archive should be written.
3. Ask whether to use `merge` or `create`.
4. Ask whether classification should be `auto` or `manual`.
5. If `manual`, ask for the rules JSON path.
6. Ask whether generated titles should use `en` or `zh`.
7. Run the sync command and inspect the JSON summary.

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

1. Start from `manual-rules.example.json`
2. adapt rules to your own domain taxonomy
3. run the script in `manual` mode
4. inspect `03 Domain/` and `Dashboard.md`
5. refine rules and rerun if needed

## Notes

- The archive is editor-agnostic Markdown. Obsidian is a target, not a hard dependency.
- Auto mode is best when you want broad semantic grouping with minimal setup.
- Manual mode is best when you already know your preferred taxonomy.

## License / Reuse

This project is licensed under the MIT License.

See:

- [LICENSE](LICENSE)
