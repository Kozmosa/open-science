---
aliases:
  - Claude Scholar
tags:
  - research-agent
  - repo-study
  - academic-workbench
source_repo: claude-scholar
source_path: /home/xuyang/code/scholar-agent/ref-repos/claude-scholar
last_local_commit: d79c34a 2026-03-14 docs(mcp): update zotero credential setup links
---
# Claude Scholar：学术研究与开发一体化个人配置系统

> [!abstract]
> Claude Scholar 不是单一工作流，而是“个人研究工作台”式配置仓库。它把学术研究、实验分析、论文写作、开发规范、Zotero MCP 和跨 CLI 兼容性打包到一套长期使用的环境里。

## 项目定位

- README 直接将其描述为面向 “academic research and software development” 的个人 Claude Code/Codex/OpenCode 配置。
- 相比只做研究的仓库，它明显更重视“研究 + 开发 + 项目管理”三者共存。
- 从时间线看，它在持续扩展：Zotero MCP、Codex CLI 支持、OpenCode 支持、hooks 重写、研究工作流扩充都在最近几个月发生。

## 仓库构成

- 本地可见 `skills/`、`agents/`、`commands/`、`hooks/`、`rules/`、`plugins/`、`scripts/` 等完整运行面。
- README 写明 32 个 skills、14 个 agents、50+ commands；根目录下的 `commands/` 还包含 `research-init`、`zotero-review`、`zotero-notes`、`analyze-results`、`rebuttal` 等研究相关入口。
- `MCP_SETUP.md` 单独存在，说明文献管理与工具接入是其一等需求，不是附属功能。

## 核心工作流

```mermaid
flowchart LR
    A[研究主题] --> B[research-ideation]
    B --> C[literature-reviewer + Zotero MCP]
    C --> D[research proposal / literature review]
    D --> E[results-analysis / experiment code]
    E --> F[ml-paper-writing]
    F --> G[paper-self-review / review-response]
    G --> H[多 CLI 日常工作台]
```

## 研究生命周期覆盖

- 前期：`research-ideation`、`literature-reviewer`、Zotero collection 管理、批量读文和 gap analysis。
- 中期：`results-analysis`、`architecture-design`、`bug-detective`、`git-workflow` 支撑实验开发与结果分析。
- 后期：`ml-paper-writing`、`paper-self-review`、`review-response`、`post-acceptance` 支撑写作、投稿和会后阶段。
- 它不像 academic-research-skills 那样固定 10 阶段，而是更偏“研究人员的常驻工作台”。

## 集成与依赖面

- 同时支持 Claude Code、Codex CLI、OpenCode，这是本目录里跨宿主能力最强的研究配置之一。
- Zotero MCP 是关键加分项，且 README 明确给出 collection 结构、导入方式和 full-text 工作流。
- `hooks/`、`rules/`、`plugins/` 说明它兼顾长期项目治理，而不是只为单次论文冲刺服务。

## 证据与样例

- 研究工作流、技能数、命令数与跨平台定位见 [claude-scholar/README.zh-CN.md](../../ref-repos/claude-scholar/README.zh-CN.md)。
- MCP 集成入口见 [claude-scholar/MCP_SETUP.md](../../ref-repos/claude-scholar/MCP_SETUP.md)。
- 技能目录见 [claude-scholar/skills](../../ref-repos/claude-scholar/skills)，代理目录见 [claude-scholar/agents](../../ref-repos/claude-scholar/agents)。
- 研究命令可见 [claude-scholar/commands](../../ref-repos/claude-scholar/commands)。
- 本地最近提交为 `d79c34a`，日期 `2026-03-14`。

## 优势

- 研究、开发、文献管理、评审回复都覆盖到，适合长期日常使用。
- Zotero MCP 与多 CLI 支持，使它比只绑定 Claude Code 的方案更有迁移性。
- 配置面完整，能把个人研究环境、代码规范和 agent 编排统一起来。

## 局限与风险

- 仓库目标很广，用户需要自己决定启用哪些部分，初次阅读成本偏高。
- 它是“个人配置系统”出发，不一定天然适合团队级标准化交付。
- 相比固定 pipeline，成果质量更依赖使用者自己的习惯与治理能力。

## 适用场景

- 需要一个可以长期陪跑的个人研究工作台，而不是只为一篇论文服务。
- 同时做文献管理、实验开发、结果分析和论文写作。
- 希望在 Claude Code、Codex CLI、OpenCode 之间保留选择权。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[projects/ai-research-skills]]
- [[projects/argusbot]]
- [[projects/academic-research-skills]]
- [[projects/everything-claude-code]]
