---
aliases:
  - EvoScientist
tags:
  - research-agent
  - repo-study
  - research-workbench
source_repo: EvoScientist
source_path: /home/xuyang/code/scholar-agent/ref-repos/EvoScientist
last_local_commit: 741eb70 2026-03-15 feat: support ANTHROPIC_BASE_URL for proxy-based deployments (e.g. ccproxy) (#25)
---
# EvoScientist：多渠道统一控制面的自进化 AI 科学家工作台

> [!abstract]
> EvoScientist 不是只做“深度研究报告”的单点工具，也不是只服务论文投稿的固定管线。结合 README、运行时目录和子代理配置看，它更像一个带统一控制面的研究工作台：把多代理协作、持久记忆、多渠道会话、多模型供应商、MCP 扩展和可安装技能整合进同一套运行时。

## 项目定位

- README 把它定义为 “Towards Self-Evolving AI Scientists” 和 “a living research system”，强调的是可持续演化的研究伙伴，而不是单次任务脚本。
- README 列出的核心特性同时覆盖 `Multi-Agent Team`、`Persistent Memory`、`Multi-Provider`、`Multi-Channel`、`Scientific Workflow`、`MCP & Skills`，说明它的主张是“统一入口的研究运行面”。
- 这类定位与 [[projects/claude-scholar]] 有部分重叠，但 EvoScientist 更偏运行时控制面和统一会话层，而不是长期个人配置集合。

## 仓库构成

- Python 包主体位于 `EvoScientist/`，目录下可直接看到 `cli/`、`channels/`、`config/`、`llm/`、`mcp/`、`middleware/`、`stream/`、`tools/` 等完整运行面。
- `subagent.yaml` 明确定义了 6 个子代理：`planner-agent`、`research-agent`、`code-agent`、`debug-agent`、`data-analysis-agent`、`writing-agent`，与 README 中的多代理叙事一致。
- `channels/` 下已拆出 Telegram、Slack、Feishu、WeChat、QQ、Discord、DingTalk、iMessage、Signal、email、bus 等目录，说明“多渠道接入”不是 README 包装，而是仓库一等能力。
- `skills/`、`mcp/`、`paths.py`、`sessions.py` 共同说明它不仅支持即时会话，还显式管理技能、外部工具、共享内存与跨 session 持久化。

## 核心工作流

```mermaid
flowchart LR
    A[CLI / TUI / Channels] --> B[EvoScientist 主代理]
    B --> C[planner / research / code / debug / analyze / write]
    C --> D[MCP tools + installable skills]
    C --> E[/memory 持久记忆]
    C --> F[/runs 与 session checkpoint]
    D --> G[plan -> execute -> evaluate -> write -> verify]
    E --> G
    F --> G
```

## 研究生命周期覆盖

- 前期：`planner-agent`、`research-agent` 和 README 中的 `intake -> plan` 叙事说明它覆盖问题澄清、方案规划和外部检索。
- 中期：`code-agent`、`debug-agent`、`data-analysis-agent` 以及 `EvoSci --workdir`、`-m run`、`serve` 等入口，说明它把执行、调试、分析和会话管理纳入统一 runtime。
- 后期：`writing-agent` 与 `Scientific Workflow` 中的 `write -> verify` 提示它覆盖结果整理与报告写作，但没有像 [[projects/academic-research-skills]] 那样把 integrity gate、peer review、revision factory 做成重管线。
- 因此它更像“端到端研究引擎 + 工作台”，而不是只做 citation-backed 报告或正式投稿流水线。

## 集成与依赖面

- 通过 `pyproject.toml` 可见它支持 Anthropic、OpenAI、Google、NVIDIA、Ollama、Tavily，并以 `deepagents` 和 LangChain/LangGraph 作为底层。
- `sessions.py` 使用全局 SQLite checkpoint 保存线程，`paths.py` 则把 `runs/`、`memory/`、`skills/`、`media/` 视为共享运行时目录，说明跨会话连续性是显式设计。
- `EvoScientist.py` 把 `/skills/`、`/memory/`、MCP tools 和 subagents 组合成统一 agent graph，并对 MCP 连接做缓存，反映出它更偏“研究运行时”而不是单个 prompt 协议。
- 默认 shell 执行带审批、支持 `ask user`、支持 `channel setup` 与 `mcp add`，这意味着它采用的是 human-on-the-loop 风格，而非完全无关卡自治。

## 证据与样例

- 项目定位、功能、安装、渠道、路线图和外部技术报告链接见 [EvoScientist/README.md](../../ref-repos/EvoScientist/README.md)。
- 中文说明可见 [EvoScientist/README.zh-CN.md](../../ref-repos/EvoScientist/README.zh-CN.md)。
- 包依赖、脚本入口和可选渠道依赖见 [EvoScientist/pyproject.toml](../../ref-repos/EvoScientist/pyproject.toml)。
- 多代理角色定义见 [EvoScientist/EvoScientist/subagent.yaml](../../ref-repos/EvoScientist/EvoScientist/subagent.yaml)。
- 共享路径与持久会话设计见 [EvoScientist/EvoScientist/paths.py](../../ref-repos/EvoScientist/EvoScientist/paths.py) 和 [EvoScientist/EvoScientist/sessions.py](../../ref-repos/EvoScientist/EvoScientist/sessions.py)。
- 运行时组装逻辑见 [EvoScientist/EvoScientist/EvoScientist.py](../../ref-repos/EvoScientist/EvoScientist/EvoScientist.py)。
- 本地最近提交为 `741eb70`，日期 `2026-03-15`。
- README 还给出了 Technical Report、DeepResearch Bench II 排名和获奖信息的外部链接；这些可作为项目自述信号，但本笔记未独立联网核验。

## 优势

- 统一运行时完成度高：CLI/TUI、channels、skills、MCP、memory、session persistence 都已落到代码和测试目录。
- 多渠道共享同一 agent session 的能力，在现有参考项目里辨识度很高，适合“研究助手随人移动”的使用方式。
- 既支持研究生命周期，又保留审批与追问机制，平衡了自治与人工在环上的控制需求。

## 局限与风险

- README 的 benchmark、奖项与技术报告叙事很强，但这些高位结论多数依赖外部链接，不能等同于本地仓库已自证。
- 运行时能力面很广，真实质量会受到模型供应商、API key、渠道配置、MCP 稳定性等外部条件影响。
- 它偏统一控制面和工作台，不等于已经提供 repo-native 的研究工件图谱、复现账本和正式投稿级质量门。

## 适用场景

- 需要一个统一入口，把多模型、多渠道、多技能、多工具和持久记忆收进同一研究工作台。
- 希望研究助手既能在本地 CLI/TUI 里工作，也能通过 Telegram、Slack、Feishu、WeChat 等渠道续接同一会话。
- 需要比 [[projects/claude-scholar]] 更强调运行时控制面，比 [[projects/claude-code-deep-research]] 更强调工作台和扩展面的方案。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[framework/reference-mapping]]
- [[projects/claude-scholar]]
- [[projects/claude-code-deep-research]]
- [[projects/academic-research-skills]]
