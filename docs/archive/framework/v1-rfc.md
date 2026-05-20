---
aliases:
  - AINRF V1 RFC
  - V1 实现规格
tags:
  - research-agent
  - framework-design
  - v1-spec
  - rfc
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AINRF V1 RFC（历史文档）

> [!warning]
> 本文档保留为历史 RFC，用于归档早期 `AINRF v1` orchestrator 方案的实现想法、接口设想和组件分层。它不再代表 `scholar-agent` 当前 next release 的主路径，也不应再被当作当前 requirements 或 architecture baseline 的入口。

> [!abstract]
> 这份 RFC 记录的，是项目曾经如何把框架蓝图翻译成 API-first orchestrator、TaskEngine、StateStore、Agent Adapter 和 execution layer 的一整套实现设想。它仍然对理解术语来源和旧版系统假设有价值，但当前项目已转向“单用户优先、task-centric、evidence-grounded 的 research dashboard”重定位，因此本文档的内容应视为历史方案，而非现行规范。

## 当前状态说明

- 本文档描述的是早期 `v1` orchestrator 方案，而不是当前 next release 的正式实现边界。
- 其中关于完整三层研究引擎、双模式编排核心、未来 UI、完整任务状态机等内容，很多属于历史蓝图叙事。
- 当前项目不再以“先实现完整 orchestrator，再逐步长出产品”作为默认推进方式。
- 新的 requirements / expectations / baseline 以 `LLM-Working/refactoring-plan/` 下的文档集为准。

## 当前应优先阅读的替代入口

如果你的目标是理解项目现在应该如何推进，请优先阅读：

- [[framework/ai-native-research-framework]]
- [[LLM-Working/refactoring-plan/index]]
- [[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]
- [[LLM-Working/refactoring-plan/mode-baseline-spec]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- [[LLM-Working/refactoring-plan/architecture-baseline-plan]]

## 本文档仍然保留的价值

- 说明早期 `TaskEngine` / `StateStore` / `GateManager` / `AgentAdapter` 这套术语如何形成。
- 记录当时对 API-first orchestrator、SSE、关卡、checkpoint/resume 的整体设想。
- 为比对当前实现与历史蓝图之间的偏差提供参考。
- 为后续需要回溯历史决策时提供证据，而不是让这些判断只存在于会话上下文里。

## 阅读注意事项

- 看到“REST 服务是 V1 的正确形态”“Orchestrator Core 是系统的大脑”“未来 UI 需要包装层”等表述时，应理解为历史方案的设计立场。
- 看到完整 task schema、SSE event taxonomy、三层架构和完整模式编排时，不要自动把它们视为当前 release 承诺。
- 本文档的很多细节可能仍对代码考古有帮助，但如果与当前 realignment 文档冲突，应以后者为准。

## 历史主题索引

- API-first 任务服务设想
- TaskEngine / StateStore / GateManager 的分层假设
- 早期的双模式 orchestrator 任务模型
- SSE 事件分类与 checkpoint/resume 想法
- 早期执行层与 Agent Adapter 抽象

## 与其他历史文档的关系

- [[framework/v1-roadmap]] 记录这套历史 RFC 当时对应的阶段化交付路径。
- [[framework/webui-v1-rfc]] 记录与该 orchestrator 思路配套的早期 WebUI 方案。
- [[framework/v1-implementation-status]] 记录历史文档与实际实现之间的阶段映射，但同样应视为历史状态记录。

## 关联笔记

- [[framework/index]]
- [[framework/ai-native-research-framework]]
- [[LLM-Working/refactoring-plan/index]]
- [[framework/v1-roadmap]]
- [[framework/webui-v1-rfc]]
