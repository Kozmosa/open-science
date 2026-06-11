# Obsidian + arXiv Integration (Optional)

> 🇨🇳 中文版：[OBSIDIAN_CN.md](OBSIDIAN_CN.md)
> Plugs into [`/research-lit`](../../skills/research-lit/SKILL.md) and the upstream skills that call it. Pairs naturally with the [Zotero integration](ZOTERO.md).

If you use [Obsidian](https://obsidian.md/) for research notes, `/research-lit` can search your vault for paper summaries, tagged references, and your own insights. These are usually more valuable than raw papers because they already encode your judgments.

## Recommended MCP server

**[mcpvault](https://github.com/bitbonsai/mcpvault)** (760⭐, no Obsidian app needed, 14 tools, BM25 search)

```bash
# Add to Claude Code (point to your vault path)
claude mcp add obsidian-vault -s user -- npx @bitbonsai/mcpvault@latest /path/to/your/vault
```

## Optional complement: obsidian-skills

**[obsidian-skills](https://github.com/kepano/obsidian-skills)** (13.6k⭐, by Obsidian CEO) — teaches Claude to understand Obsidian-specific Markdown (wikilinks, callouts, properties). Copy to your vault:

```bash
git clone https://github.com/kepano/obsidian-skills.git
cp -r obsidian-skills/.claude /path/to/your/vault/
```

## What it enables in `/research-lit`

- 🔍 Search your vault for notes on the research topic
- 🏷️ Find notes by tags (e.g., `#paper-review`, `#diffusion-models`)
- 📝 Read your processed summaries and insights (more valuable than raw papers)
- 🔗 Follow wikilinks to discover related notes

## Fallback: no Obsidian

Without Obsidian configured, `/research-lit` automatically skips it and works as before. No errors, no warnings.

## Combined Zotero + Obsidian workflow

Many researchers use Zotero for paper storage and Obsidian for notes. Both integrations work simultaneously — `/research-lit` checks Zotero first (raw papers + annotations), then Obsidian (your processed notes), then local PDFs, then web search. See [ZOTERO.md](ZOTERO.md) for the Zotero half.

---

## arXiv (built-in, no setup)

`/research-lit` automatically queries the arXiv API for structured metadata (title, abstract, full author list, categories) — richer than web search snippets. **No setup required.**

By default, only metadata is fetched (no files downloaded). To also download the most relevant PDFs:

```
/research-lit "topic" — arxiv download: true                    # download top 5 PDFs
/research-lit "topic" — arxiv download: true, max download: 10  # download up to 10
```

For standalone arXiv access, use the dedicated [`/arxiv`](../../skills/arxiv/SKILL.md) skill:

```
/arxiv "attention mechanism"           # search
/arxiv "2301.07041" — download         # download specific paper
```

## Related skills

- [`/research-lit`](../../skills/research-lit/SKILL.md) — primary consumer
- [`/arxiv`](../../skills/arxiv/SKILL.md) — standalone arXiv search/download
- [`/idea-discovery`](../../skills/idea-discovery/SKILL.md) — uses `/research-lit` internally
