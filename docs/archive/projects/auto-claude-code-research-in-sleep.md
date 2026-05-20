---
aliases:
  - Auto-claude-code-research-in-sleep
  - ARIS
tags:
  - research-agent
  - repo-study
  - autonomous-research
source_repo: Auto-claude-code-research-in-sleep
source_path: /home/xuyang/code/scholar-agent/ref-repos/Auto-claude-code-research-in-sleep
last_local_commit: c4016ec 2026-03-14 docs: warn users to set gpt-5.4 in Codex config
---
# Auto-claude-code-research-in-sleep：过夜自治科研流水线

> [!abstract]
> 这个项目最鲜明的标签不是“技能库”，而是“把研究循环交给模型过夜跑”。它用 Claude Code 负责执行，用外部 LLM 通过 Codex MCP 承担批判式 reviewer 角色，强调跨模型协作而不是单模型自我博弈。

## 项目定位

- 仓库主张是“Let Claude Code do research while you sleep”，重点是研究自治和长链路串联。
- README 定义了 3 条主工作流：`/idea-discovery`、`/auto-review-loop`、`/paper-writing`，并可组合成 `/research-pipeline`。
- 设计哲学是“speed × rigor”：Claude Code 执行快，Codex/GPT-5.4 负责更慢但更严谨的审查。

## 仓库构成

- 本地 `skills/` 下有 21 个技能目录，覆盖找 idea、文献调研、novelty check、实验执行、论文写作、review loop、Feishu 通知等。
- 存在 `mcp-servers/minimax-chat/`，说明它并不完全绑定 OpenAI 组合，也考虑替代模型接入。
- `docs/` 和 `assets/` 中放了流程图、评分曲线、通知截图等展示材料，强调实际运行体验。

## 核心工作流

```mermaid
flowchart LR
    A[研究方向输入] --> B[/idea-discovery]
    B --> C[文献检索与 novelty check]
    C --> D[实验设计与运行]
    D --> E[/auto-review-loop]
    E --> F[外部模型批判式审查]
    F --> G[迭代改实验与改论证]
    G --> H[/paper-writing]
    H --> I[LaTeX/PDF 产出]
    I --> J[可选 Feishu/Obsidian/Zotero 集成]
```

## 研究生命周期覆盖

- 前期覆盖较强：文献调研、idea discovery、novelty check 和研究计划都已经产品化。
- 中期覆盖实验执行：`run-experiment`、`monitor-experiment`、`analyze-results` 说明它希望真实驱动 GPU/远程实验，而不只是写报告。
- 后期覆盖写作与审阅：`paper-plan`、`paper-write`、`paper-compile`、`auto-paper-improvement-loop` 连接成论文成稿回路。
- 在“从方向到论文”的完整性上，它是本目录里最强调自治迭代的项目之一。

## 集成与依赖面

- 安装方式是把 `skills/*` 复制到 `~/.claude/skills/`，说明其主要宿主仍是 Claude Code。
- 高价值能力依赖 Codex MCP，README 还专门提醒模型配置来自 `~/.codex/config.toml`。
- 可选集成面很多：Zotero、Obsidian、本地 PDF、Feishu/Lark、远程服务器、多模型组合，这让能力更强，也显著推高初始配置复杂度。

## 证据与样例

- 工作流、功能亮点、远程服务器和集成项见 [Auto-claude-code-research-in-sleep/README_CN.md](../../ref-repos/Auto-claude-code-research-in-sleep/README_CN.md)。
- 技能清单见 [Auto-claude-code-research-in-sleep/skills](../../ref-repos/Auto-claude-code-research-in-sleep/skills)。
- 替代模型和 MCP 方向可从 [Auto-claude-code-research-in-sleep/mcp-servers](../../ref-repos/Auto-claude-code-research-in-sleep/mcp-servers) 观察。
- 本地最近提交为 `c4016ec`，日期 `2026-03-14`。

## 优势

- 工作流完整，能把“找方向、做实验、写论文、反复 review”串成一条自动链路。
- 跨模型 reviewer 设计有明确理论立场，避免单模型自审的盲点。
- 对实验、通知、远程执行这些现实科研摩擦点有直接设计，而不是只停留在写作层。

## 局限与风险

- 外部依赖多，包含 Claude、Codex、可选 MCP、可选远程 GPU，部署门槛明显高于 prompt 型项目。
- 质量叙事高度依赖 README 中展示的 run story，本地仓库本身仍以技能文档和操作说明为主。
- 长链路自治适合熟手，不适合把每一步都需要强控制的人。

## 适用场景

- 有明确研究方向，希望把 nightly loop、交叉模型审查和实验执行串起来。
- 需要“研究助手 + reviewer”双角色分工，而不是单一模型全包。
- 对 Feishu、Zotero、Obsidian 一类研究配套工具有真实接入需求。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[projects/argusbot]]
- [[projects/claude-code-deep-research]]
- [[projects/academic-research-skills]]
- [[projects/claude-scholar]]
