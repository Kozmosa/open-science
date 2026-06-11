# Obsidian + arXiv 集成（可选）

> 🇬🇧 English: [OBSIDIAN.md](OBSIDIAN.md)
> 接入 [`/research-lit`](../../skills/research-lit/SKILL.md) 以及调用它的上游 skill。和 [Zotero 集成](ZOTERO_CN.md) 天然搭配。

如果你用 [Obsidian](https://obsidian.md/) 做研究笔记，`/research-lit` 可以搜索你的 vault 中的论文总结、带标签的引用和你自己的洞察。这些通常比原始论文更有价值，因为已经包含了你的判断。

## 推荐的 MCP server

**[mcpvault](https://github.com/bitbonsai/mcpvault)**（760⭐，不需要打开 Obsidian，14 个工具，BM25 搜索）

```bash
# 添加到 Claude Code（指向你的 vault 路径）
claude mcp add obsidian-vault -s user -- npx @bitbonsai/mcpvault@latest /path/to/your/vault
```

## 可选补充：obsidian-skills

**[obsidian-skills](https://github.com/kepano/obsidian-skills)**（13.6k⭐，Obsidian CEO 维护）—— 让 Claude 理解 Obsidian 特有的 Markdown 格式（wikilinks、callouts、properties）。复制到你的 vault：

```bash
git clone https://github.com/kepano/obsidian-skills.git
cp -r obsidian-skills/.claude /path/to/your/vault/
```

## 启用后 `/research-lit` 新增能力

- 🔍 搜索 vault 中与研究主题相关的笔记
- 🏷️ 按标签查找笔记（如 `#paper-review`、`#diffusion-models`）
- 📝 读取你的加工后总结和洞察（比原始论文更有价值）
- 🔗 沿 wikilinks 发现相关笔记

## 不用 Obsidian？

没配置时 `/research-lit` 自动跳过，照常工作。无报错无警告。

## Zotero + Obsidian 组合工作流

很多研究者用 Zotero 存论文、Obsidian 记笔记。两个集成可以同时工作——`/research-lit` 先查 Zotero（原始论文 + 标注），再查 Obsidian（加工后笔记），再查本地 PDF，最后搜网络。Zotero 半边的配置见 [ZOTERO_CN.md](ZOTERO_CN.md)。

---

## arXiv（内置，无需配置）

`/research-lit` 会自动通过 arXiv API 获取结构化元数据（标题、摘要、完整作者列表、分类），比网页搜索片段更丰富。**无需任何配置。**

默认只获取元数据（不下载文件）。如需同时下载最相关的 PDF：

```
/research-lit "topic" — arxiv download: true                    # 下载 top 5 篇 PDF
/research-lit "topic" — arxiv download: true, max download: 10  # 下载至多 10 篇
```

也可使用独立的 [`/arxiv`](../../skills/arxiv/SKILL.md) skill 直接搜索和下载：

```
/arxiv "attention mechanism"           # 搜索
/arxiv "2301.07041" — download         # 下载指定论文
```

## 相关 skill

- [`/research-lit`](../../skills/research-lit/SKILL.md) —— 主要消费者
- [`/arxiv`](../../skills/arxiv/SKILL.md) —— 独立 arXiv 搜索/下载
- [`/idea-discovery`](../../skills/idea-discovery/SKILL.md) —— 内部调用 `/research-lit`
