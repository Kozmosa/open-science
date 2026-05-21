---
aliases:
  - Claude Code Deep Research
tags:
  - research-agent
  - repo-study
  - deep-research
source_repo: Claude-Code-Deep-Research-main
source_path: /home/xuyang/code/scholar-agent/ref-repos/Claude-Code-Deep-Research-main
last_local_commit: 2120f68 2025-12-30 fix
---
# Claude Code Deep Research：多阶段深度研究框架

> [!abstract]
> 这是一个更“收敛”的深度研究仓库：它不试图覆盖完整科研生产线，而是集中做问题澄清、研究规划、并行执行、结果综合和引文验证，产物是 citation-backed 的研究报告。

## 项目定位

- README 直接把自己描述为“implements OpenAI's Deep Research and Google Gemini's Deep Research capabilities using Claude Code's native features”。
- 项目强调 `Graph of Thoughts (GoT)`、7 阶段 deep research 流程、多 agent 架构和 citation validation。
- 它的目标输出不是论文成稿，而是主题研究报告和结构化研究产物目录。

## 仓库构成

- 关键入口都放在 `.claude/`：5 个 skills 目录和 5 个 commands 文件，结构清晰、边界明确。
- `RESEARCH/` 下已经包含多个示例输出目录，说明作者把“研究结果文件夹”作为第一类产物。
- 没有庞杂插件生态，也没有大量通用开发能力，仓库聚焦度较高。

## 核心工作流

```mermaid
flowchart TD
    A[/refine-question] --> B[/plan-research]
    B --> C[/deep-research]
    C --> D[research-executor]
    D --> E[got-controller]
    E --> F[synthesizer]
    F --> G[/synthesize-findings]
    G --> H[/validate-citations]
    H --> I[RESEARCH/topic/full_report.md]
```

## 研究生命周期覆盖

- 覆盖“问题收束到研究报告”这一段，而不是从研究创意到论文投稿的整条链。
- 在研究中段，它最强调并行调查与结构化综合，而不是实验训练、GPU 调度或 paper drafting。
- 它的 differentiator 是 source quality rating 和 chain-of-verification，而不是写作 polish。

## 集成与依赖面

- 使用前提很简单：Claude Code CLI + `.claude/` 目录内已有 commands/skills。
- 输出位置固定到 `RESEARCH/[topic]/`，包含 `executive_summary.md`、`full_report.md`、`sources/` 等子结构，适合做标准化研究归档。
- 相比多模型、多 MCP 的方案，它的依赖面更薄，但可扩展空间也更受限。

## 证据与样例

- 项目定位、GoT、commands reference 和输出目录结构见 [Claude-Code-Deep-Research-main/README.md](../../ref-repos/Claude-Code-Deep-Research-main/README.md)。
- 编排入口见 [Claude-Code-Deep-Research-main/.claude/commands](../../ref-repos/Claude-Code-Deep-Research-main/.claude/commands)。
- 核心 skill 目录见 [Claude-Code-Deep-Research-main/.claude/skills](../../ref-repos/Claude-Code-Deep-Research-main/.claude/skills)。
- 示例结果可见 [Claude-Code-Deep-Research-main/RESEARCH](../../ref-repos/Claude-Code-Deep-Research-main/RESEARCH)。
- 本地最近提交为 `2120f68`，日期 `2025-12-30`。

## 优势

- 单点目标清晰，容易理解和部署。
- 引文验证和研究输出目录是显式设计，不是运行后临时拼装。
- 适合把“深度研究”能力作为独立子系统接入更大的 agent 工作流。

## 局限与风险

- 不覆盖论文写作、投稿、答辩或长期实验管理。
- 生态和扩展面相对较小，主要依赖 Claude Code 原生机制。
- 本地更新时间较其他仓库偏早，活跃度信号略弱。

## 适用场景

- 需要快速得到结构化深度研究报告，而不是论文全流程。
- 需要先把研究问答和 citation-backed synthesis 独立出来，再接其他写作或实验系统。
- 想控制依赖复杂度，不愿意一开始就接入多个 MCP 和外部模型。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[projects/auto-claude-code-research-in-sleep]]
- [[projects/academic-research-skills]]
- [[projects/ai-research-skills]]
