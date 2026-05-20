---
aliases:
  - 参考项目到框架映射
tags:
  - research-agent
  - framework-design
  - summary
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# 参考项目到框架映射（历史文档）

> [!warning]
> 本文档保留为历史映射材料。它总结的是项目早期如何把外部参考仓库吸收到 `AI-Native Research Framework` 蓝图中，不再是当前文档体系的主阅读入口。

> [!abstract]
> 这份映射笔记仍然有助于理解旧版框架叙事为何吸收了平台层、控制层、能力层、编排层和工作台等不同来源，但当前项目已经不再以这套整合后的框架蓝图作为 next release 主路径。因此，本文档应视为设计追溯材料，而不是当前 requirement。

## 总览结论

- `everything-claude-code` 主要贡献平台层思路，不应被误当成研究流程本身。
- `AI-Research-SKILLs` 证明“研究能力应该模块化”，但它把太多编排责任留给宿主，因此不能直接当框架主体。
- `Claude Code Deep Research` 最适合贡献阅读、综合和 citation discipline。
- `ARIS` 最适合贡献长链路编排、探索循环和跨模型审查。其 nightly loop 与研究扩展节奏直接启发了 Mode 1 的递归调研发现，区别在于我们附加了终止合同（深度/预算/递减收益）而非开放式自治。
- `academic-research-skills` 最适合贡献 integrity 和 review gate 思维，而不是整套投稿工厂。
- `ArgusBot` 最适合贡献监督回路、planner/reviewer 双关卡和可恢复控制面，而不是研究内容能力。
- `claude-scholar` 最适合贡献多宿主工作台和长期研究环境视角。
- `EvoScientist` 最适合贡献统一运行面思路：多渠道共享 session、持久记忆、技能/MCP 扩展面和 human-on-the-loop 式审批/追问机制。
- `autoresearch` 最适合贡献"固定预算实验原语 + 单标量评估 + git-native 追踪"思路，作为 Mode 1 递归调研中轻量验证与研究节奏控制的参考。

## 框架映射矩阵

| 项目 | 在框架中的角色 | 应吸收的部分 | 不直接复制的部分 |
| --- | --- | --- | --- |
| [[projects/everything-claude-code]] | 平台底盘参考 | hooks、rules、验证门、多宿主适配思路 | 把研究能力继续当通用 skill 附属品 |
| [[projects/ai-research-skills]] | 能力包参考 | 研究能力模块化、工具/框架级技能颗粒度 | 缺少统一工件状态与编排核心 |
| [[projects/claude-code-deep-research]] | 阅读与综合参考 | question refinement、citation-backed synthesis、标准化产物目录 | 只做到报告，不覆盖复现与实验追踪 |
| [[projects/auto-claude-code-research-in-sleep]] | 编排与执行参考 | nightly loop、run-experiment、探索循环、终止模式、外部 reviewer、研究闭环意识 | 无约束自治默认值；框架用终止合同替代 |
| [[projects/academic-research-skills]] | 质量门参考 | integrity、review、revision、formal verification | V1 不做完整投稿与返修工厂 |
| [[projects/argusbot]] | 控制层参考 | reviewer/planner gating、有界执行阶段的 reviewer 约束、daemon bus、resume continuity | 不复制 `--yolo` 默认和 Codex 专属假设 |
| [[projects/claude-scholar]] | 工作台参考 | 多 CLI、Zotero/MCP、长期个人研究环境 | 个人配置系统不等于平台核心模型 |
| [[projects/evoscientist]] | 统一运行面参考 | 多渠道共享会话、持久记忆、skills/MCP 一等扩展、审批与追问机制 | deepagents 绑定、偏聊天工作台的运行时假设、README 中未独立核验的 benchmark/奖项叙事 |
| [[projects/autoresearch]] | 实验原语参考 | 固定预算实验、单标量评估、git-native 追踪、简洁性准则 | 窄域单指标、无研究前后端、无协作 |

## 结构化借鉴

- 平台层优先借鉴 [[projects/everything-claude-code]] 和 [[projects/claude-scholar]] 的宿主兼容与长期治理观；运行时交互面则补借鉴 [[projects/evoscientist]] 的统一 session、memory 与扩展面设计。
- 控制层优先借鉴 [[projects/argusbot]] 的监督回路、计划快照与可恢复运行面。
- 能力层优先借鉴 [[projects/ai-research-skills]] 的技能颗粒度，再用 [[projects/claude-code-deep-research]] 补阅读与证据纪律。
- 编排层优先借鉴 [[projects/auto-claude-code-research-in-sleep]] 的执行链条和探索循环，用终止合同（深度/预算/递减收益）替代其无约束自治默认。还可借鉴 [[projects/autoresearch]] 的固定预算 + 单标量评估 + git-native 追踪模式，作为调研节奏控制与轻量验证原语的参考。
- 质量层优先借鉴 [[projects/academic-research-skills]] 的 integrity 观，而不是直接移植其重写作管线。

## 关键取舍

- 我们选“工件图谱系统”，而不是“技能市场”，因为后者无法给 `PaperCard`、`ReproductionTask`、`ExperimentRun` 一个统一状态语义。
- 我们选”有界自治”（depth/budget/time/agent 自评递减收益），而不是”无约束自治”或”逐步审批”。系统可以过夜运行，但在合同之内——不是空白支票，也不是每一步都停下来问人。
- 我们选“repo 优先”，而不是“知识库优先”，因为平台团队真正需要的是可移交、可审计、可重跑的研究资产。

## 关联笔记

- [[framework/index]]
- [[framework/ai-native-research-framework]]
- [[framework/artifact-graph-architecture]]
- [[framework/v1-dual-mode-research-engine]]
- [[framework/container-workspace-protocol]]
- [[summary/academic-research-agents-overview]]
- [[projects/argusbot]]
- [[projects/academic-research-skills]]
- [[projects/evoscientist]]
- [[projects/autoresearch]]
