# Domain Policy

## Purpose

Classify X likes JSON into a local Markdown knowledge archive.
Output is editor-agnostic Markdown (Obsidian-friendly).

## Auto Classification

Auto mode must use JSON signals:
- content text (`full_text`)
- metadata entities (hashtags, expanded URLs, media)
- URL host signals
- media type signals

Auto mode should also normalize semantic duplicates (for example: `Agent自动化` and `Agent与自动化`).

## Domain Structure Constraints

- Root: `01 Date`, `02 Author`, `03 Domain`, `Dashboard.md`
- Domain top-level count: `<= 20`
- Domain max depth: `<= 8`
- Domain leaf files should stay `<= 100` posts; if exceeded, split further by semantic/content buckets
- Parent `Index.md` files exist only for hierarchical folders
- Leaf categories are markdown files, not `folder + Index.md`

## Suggested Top-Level Domains

- `AI`
- `技术与开发`
- `工具与效率`
- `数码与设备`
- `商业与经济`
- `金融与投资`
- `学习与教育`
- `健康与生活`
- `设计与创意`
- `社会与公共议题`
- `文化与娱乐`
- `其他`

## AI Subtree Examples

- `编程助手`
- `Agent与自动化`
- `模型与提示词`
- `产品与应用`
- `图像与视频`
- `资讯与研究`

## Manual Classification

Manual rules remain first-match.
`domain` can be nested with `/` and is normalized by semantic alias rules.
