# convert-x-likes-to-markdown

[![README-English](https://img.shields.io/badge/README-English-555555?style=for-the-badge)](README.md)
[![README-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87](https://img.shields.io/badge/README-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-2d6cdf?style=for-the-badge)](README.zh-CN.md)

把 X（Twitter）点赞导出 JSON 转换成一个本地 Markdown 归档。

这个仓库同时包含两部分：

- 一份 Codex skill 定义（`SKILL.md`）
- 一个可独立运行的同步脚本（`scripts/sync_x_likes.py`）

输出是普通 Markdown，但结构专门针对 Obsidian 这类工作流做了优化，便于：

- 按日期浏览
- 按作者浏览
- 按领域/主题浏览
- 通过仪表盘查看整体统计

## 项目作用

给定一份 X Likes 导出的 JSON 文件，这个工具可以：

- 把点赞内容解析成标准化记录
- 把每条点赞内容写成一条 Markdown 笔记
- 按日期、作者、语义领域组织索引
- 通过 `create` 从头重建归档
- 通过 `merge` 增量并入已有归档
- 通过 `auto` 使用 JSON 信号自动分类
- 通过 `manual` 使用自定义规则分类
- 生成英文或中文标题与索引名称

## 仓库结构

```text
convert-x-likes-to-markdown/
├── README.md
├── README.zh-CN.md
├── LICENSE
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

## 运行要求

- Python 3
- 一份导出的 X Likes JSON 文件

不需要额外安装第三方 Python 依赖。

## 如何获得输入 JSON

这个项目本身不负责直接从 X 抓取数据，它的前提是你先拿到一份导出的 JSON 文件。

推荐使用的上游导出工具是：

- [prinsss/twitter-web-exporter](https://github.com/prinsss/twitter-web-exporter)

推荐流程：

1. 先安装 Tampermonkey 或 Violentmonkey 这类 userscript 管理器。
2. 安装 `twitter-web-exporter` 的 userscript。
3. 在 X/Twitter 网页端打开你要导出的页面，例如 Likes 页面。
4. 向下滚动，直到你想导出的数据都已经在页面里加载出来。
5. 用导出面板把当前捕获的数据导出为 `JSON`。
6. 再把这份 JSON 文件交给本仓库的 `sync_x_likes.py` 使用。

需要注意：

- 本仓库不会直接抓取 X
- 本仓库的起点是一份已经导出的 JSON 文件
- 导出内容是否完整，取决于网页端实际加载了多少数据

## 输入

脚本输入是一份导出的 X Likes JSON 文件。

示例：

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto
```

## 输出结构

输出总是写到：

```text
<target-root>/<container-name>/
```

默认 `container-name`：

```text
X Likes
```

生成结构如下：

```text
X Likes/
├── 01 Date/
├── 02 Author/
├── 03 Domain/
└── Dashboard.md
```

### 顶层目录含义

- `01 Date/`
  按年/月浏览点赞笔记。
- `02 Author/`
  按作者账号浏览点赞笔记。
- `03 Domain/`
  按语义领域或主题层级浏览点赞笔记。
- `Dashboard.md`
  总览页，包含数量统计、月份分布、领域分布和导航入口。

## 工作模式

### `create`

只根据本次提供的 JSON 文件重建归档。

适合你想从头生成一套干净结果的时候使用。

### `merge`

先读取已有 Markdown 笔记，再把新输入合并进现有归档。

适合增量更新已有归档。

## 分类模式

### `auto`

自动分类模式会使用导出 JSON 中的信号，包括：

- 帖子正文
- URL 域名信号
- hashtags 与 entities
- 媒体类型信号

它不是简单关键词映射，而是会做语义归类，并尽量归并相近分类。

参考策略：

- [references/domain-policy.md](references/domain-policy.md)

### `manual`

手工分类模式会使用你提供的一份 first-match 规则 JSON。

示例规则文件：

- [references/manual-rules.example.json](references/manual-rules.example.json)

示例命令：

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/manual-rules.json" \
  --title-language zh
```

## 命令参考

### 自动分类

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto \
  --title-language en
```

### 手工分类

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification manual \
  --manual-rules "/path/to/manual-rules.json" \
  --title-language zh
```

### 参数说明

- `--input-json`
  X Likes 导出 JSON 路径。
- `--target-root`
  输出根目录，归档容器会创建在其下面。
- `--container-name`
  `target-root` 下的归档目录名，默认是 `X Likes`。
- `--mode`
  必填。`merge` 或 `create`。
- `--classification`
  必填。`auto` 或 `manual`。
- `--title-language`
  可选。`en` 或 `zh`，默认 `en`。
- `--manual-rules`
  当 `--classification manual` 时必填。

## 生成规则

- 顶层根名称固定为：`01 Date`、`02 Author`、`03 Domain`、`Dashboard.md`
- 如果标题提取失败：
  - 英文回退为 `Post <last6>`
  - 中文回退为 `帖子 <last6>`
- 领域叶子节点是 Markdown 文件，不是 `文件夹 + Index.md`
- 领域层级深度会被限制，避免目录过深

## 输出校验保证

脚本写入完成后会验证这些约束：

- 根目录只包含 `01 Date`、`02 Author`、`03 Domain`、`Dashboard.md`
- `final_tweet_notes == final_notes`
- 一级领域数量不超过脚本限制
- 最大领域深度不超过脚本限制
- 超大领域叶子会被重新平衡拆分

当前脚本内置限制：

- 一级领域上限：`20`
- 最大领域深度：`8`
- 领域叶子文件最大容量阈值：`100`

## 手工规则示例

见：

- [references/manual-rules.example.json](references/manual-rules.example.json)

这个示例展示了：

- fallback domain/tag
- 基于关键词的领域路由
- topic tag 提取

## 作为 Codex Skill 使用

这个仓库同时提供了一份 Codex skill 定义：

- [SKILL.md](SKILL.md)

推荐交互流程：

1. 询问用户 JSON 路径
2. 询问归档输出位置
3. 询问使用 `merge` 还是 `create`
4. 询问使用 `auto` 还是 `manual`
5. 如果选 `manual`，再询问规则 JSON 路径
6. 询问标题输出语言使用 `en` 还是 `zh`
7. 运行同步命令并检查 JSON summary

skill 注册配置见：

- [agents/openai.yaml](agents/openai.yaml)

## 典型使用流程

### 首次生成

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/likes.json" \
  --target-root "/path/to/output" \
  --mode create \
  --classification auto \
  --title-language en
```

### 后续增量更新

```bash
python3 scripts/sync_x_likes.py \
  --input-json "/path/to/new-likes.json" \
  --target-root "/path/to/output" \
  --mode merge \
  --classification auto \
  --title-language en
```

### 手工分类工作流

1. 先从 `manual-rules.example.json` 开始
2. 按自己的领域体系修改规则
3. 用 `manual` 模式运行脚本
4. 检查 `03 Domain/` 和 `Dashboard.md`
5. 根据结果继续调规则并重跑

## 备注

- 输出是编辑器无关的 Markdown，Obsidian 只是重点目标之一
- `auto` 适合希望少配置、快速获得大致语义归类的场景
- `manual` 适合已经有明确分类体系的场景

## 许可证

本项目使用 MIT License。

见：

- [LICENSE](LICENSE)
