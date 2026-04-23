---
aliases:
  - Architecture Baseline Plan
  - Architecture Baseline 规划
tags:
  - scholar-agent
  - architecture
  - implementation-plan
  - dashboard
source_repo: scholar-agent
source_path: /Users/kozmosa/code/scholar-agent
last_local_commit: workspace aggregate
---
# Architecture Baseline 规划

> [!abstract]
> 本文档用于把 `scholar-agent` 的 next release 架构从“未来态研究引擎蓝图”收敛为“围绕单用户 research dashboard 的可实现控制面架构”。目标不是重写现有 `[[framework/v1-rfc]]`，而是基于当前已经落地的 `ainrf` 控制面能力，固定 next release 的核心对象、模块边界、前后端契约、must-have 数据面和明确延期项，从而给后续真正的 architecture 文档和实现切片提供稳定基线。

> [!note]
> 本文档仍保留 baseline 价值，但其中早期使用的 `gates / events / artifacts` vocabulary 已经部分落后于当前目录现实。当前产品面应以 `task_harness / tasks / workspaces / terminal / environments / code_server` 为主，并以 [[ainrf/index]] 与 `src/ainrf/README.md` 作为事实层入口。

## 规划结论

- next release 的架构必须围绕 `task-centric operator control plane` 组织，而不是围绕未来态完整 research runtime 组织。
- 当前 `ainrf` 已有的 API、state、task_harness、tasks、workspaces、terminal、environment control plane 与 SSH health 基础，应被视为 next release 的真实起点，而不是被新架构推倒重来。
- architecture 的核心对象应收敛为：task、workspace、session、container、artifact preview、resource snapshot。
- 任何需要完整 TaskEngine、完整 experiment runtime、全局 analytics 或多用户权限系统才能成立的设计，都必须延期。

## 与现有文档的关系

### 与 Framework 的关系

- `[[framework/ai-native-research-framework]]` 负责解释项目为什么存在、为什么有用、边界在哪里。
- `[[framework/v1-dual-mode-research-engine]]` 保留蓝图层意义，但不直接约束 next release。
- 本文档只负责 next release 的实现边界，不负责长期愿景扩展。

### 与 RFC 的关系

- `[[framework/v1-rfc]]` 仍然是未来态和实现蓝图的重要来源。
- 但 next release 不直接照搬 RFC 的完整三层研究引擎叙事。
- 本文档优先以“当前已有实现 + next release 必交付功能”为准，必要时显式压缩 RFC 范围。

### 与 Baseline Specs 的关系

- `[[LLM-Working/refactoring-plan/mode-baseline-spec]]` 定义 Mode 1 / Mode 2 的 next release 边界。
- `[[LLM-Working/refactoring-plan/dashboard-baseline-spec]]` 定义 dashboard 的 next release 边界。
- 本文档把这两个 baseline 转换成实现结构与模块责任。

## 架构目标

### 必须实现的目标

- 支撑一个单用户优先的 task-centric dashboard。
- 支撑 Mode 1 / Mode 2 baseline 的任务创建、状态推进、结果回看与归档。
- 支撑 workspace / session / container 上下文的可见性。
- 支撑 artifact preview 与资源快照。
- 支撑系统健康、任务 timeline 和 recent artifacts 的统一呈现。

### 不应试图在 next release 解决的目标

- 完整 research runtime 自动化。
- 完整 ExperimentRun orchestration。
- 开放式多轮自治研究。
- 全局知识图谱和 artifact graph 浏览。
- 多用户和团队协作。

## 核心对象模型

### 1. Task

- task 是一级对象，也是前后端 contract 的中心。
- 所有首页列表、详情页、timeline、termination summary 都围绕 task 组织。

next release 中 task 至少应包含：

- 基本标识：id、mode、created_at、updated_at。
- 生命周期：status、stage、termination_reason。
- 输入摘要：topic / seed paper / target paper / target result 的轻摘要。
- 运行摘要：current checkpoint、active gate、artifact summary。

### 2. Workspace

- workspace 是 task 的执行和产物归属上下文，不是独立产品对象。
- 在 next release 中，workspace 的主要职责是：让 dashboard 能展示“这个 task 在哪个工作区里运行、消耗了哪些资源、产出了哪些工件”。

### 3. Session

- session 是当前 task 与 container / execution context 的连接状态抽象。
- 在 next release 中，session 不应被设计成复杂的多会话编排系统。
- 它只需要支撑：当前是否可连接、是否可恢复、是否可观察。

### 4. Container

- container 是资源与执行环境来源，不是 next release 的编排中心。
- next release 只要求 container 对 dashboard 可见、可诊断、可通过 SSH 建立上下文。
- container lifecycle management 继续保持 out of scope。

### 5. Artifact Preview

- artifact 在 next release 中不是图谱浏览对象，而是 task 结果的可预览载体。
- preview contract 只覆盖 tables / reports / figures 三类核心结果。

### 6. Resource Snapshot

- 资源信息不是完整可观测平台，而是 workspace / container 的轻量 snapshot。
- next release 中只要求对 dashboard 可见，不要求复杂时间序列分析。

## 模块边界

### A. Control Plane Backend

负责：

- task list / task detail / task lifecycle summary。
- gate actions。
- event timeline。
- artifact summary 与 preview metadata。
- workspace / session / container 基础状态。
- health 和 resource snapshot。

不负责：

- 完整研究算法编排。
- 高级自治策略。
- 全局分析平台。

### B. Dashboard Frontend

负责：

- 首页区块组织。
- task 详情页。
- artifact preview modal。
- timeline 与 recent lists 的呈现。
- 轻量交互：选择 task、查看详情、预览工件、查看健康状态。

不负责：

- 图形化任务编排。
- 图谱探索器。
- 内容编辑器。

### C. Execution Context Integration

负责：

- 当前 workspace / session / container 是否可用。
- 资源 snapshot。
- 与 task 的关联展示。

不负责：

- next release 中不引入新的大规模 infra orchestrator。
- 不把 SSH integration 变成多节点调度系统。

## 当前实现现实与架构策略

### 已有基础

- FastAPI service。
- task harness / tasks 路由与 task 运行时。
- workspaces / terminal / code-server 控制面。
- environments 配置与 SSH health / container config 基础。
- 本地 state root / runtime 持久化。

### 架构策略

- 优先复用现有控制面基础，而不是发明一套与当前 `ainrf` 脱节的新模型。
- architecture 文档必须承认 next release 是“control plane first”，而不是“runtime-first”。
- 所有新增设计都应尽量作为现有 task_harness、tasks、workspaces、terminal、state、health 能力的扩展，而不是并行体系。

## Frontend / Backend Contract Baseline

### 首页至少需要的后端数据面

1. system health summary
2. running task summary
3. running task timeline / checkpoints
4. recent finished tasks
5. recent artifacts
6. workspace resource snapshot

### 任务详情页至少需要的后端数据面

1. task summary
2. timeline / event summary
3. artifact list + preview metadata
4. workspace / session / container summary
5. termination / error summary

### Preview Contract

next release 中后端对 preview 至少需要能区分：

- table artifact
- report artifact
- figure artifact

并提供：

- artifact type
- display title
- preview format
- preview source path or equivalent payload reference

## 推荐的架构切片顺序

### Slice 1：Task-Centric Read Model

- 固定首页和详情页真正消费哪些 task 字段。
- 避免 UI 直接依赖未来态 artifact graph 或完整 runtime schema。

### Slice 2：Workspace / Session / Container Summary

- 定义 dashboard 需要看到的最小 execution context。
- 不把 execution context 设计成独立编排系统。

### Slice 3：Artifact Preview Contract

- 为 tables / reports / figures 定义统一 preview 元信息。
- 优先服务 modal preview，而不是大而全内容中心。

### Slice 4：Observability Contract

- 固定 milestone / checkpoint / event summary 如何被前端消费。
- 把精细 telemetry 作为候选项，而不是硬依赖。

## 当前最需要警惕的架构风险

### 1. 被旧 RFC 拖回完整研究引擎叙事

- 如果 architecture 继续按完整 TaskEngine、完整 execution loop、完整 experiment runtime 展开，next release 会重新失控。

### 2. 过早为前端引入复杂 telemetry 体系

- 如果为了 token usage、资源趋势和全局分析去重构大量后端，next release 的 ready-for-use 目标会被拖慢。

### 3. 把 workspace / session / container 过度平台化

- 当前需求是“可见、可诊断、可关联”，不是“云原生任务平台”。

## 明确 Deferred

- 完整 TaskEngine 重构。
- experiment runtime streaming 全量协议。
- 全局 analytics / trends / forecasting。
- 多用户权限模型。
- artifact graph explorer。
- 可视化 workflow builder。

## 对后续文档的回写要求

- manifesto 需要把本文视为 next release 的实现边界补充。
- roadmap 需要把本文中的架构切片映射成原子任务。
- 后续正式 architecture 文档应以本文为提纲，而不是重新发明结构。
- contracts 与当前实现的落差以 `[[LLM-Working/refactoring-plan/contracts-to-current-ainrf-gap-plan]]` 为准。

## 当前建议的后续原子任务

1. 固定 task read model 给 dashboard 的字段清单。
2. 固定 workspace / session / container summary shape。
3. 固定 artifact preview metadata shape。
4. 决定 token telemetry 是否延期。
5. 起草正式 architecture 文档目录。

## 当前契约入口

- task 读模型以 `[[LLM-Working/refactoring-plan/task-read-model-contract]]` 为准。
- workspace / session / container 摘要以 `[[LLM-Working/refactoring-plan/workspace-session-container-summary-contract]]` 为准。
- artifact preview 以 `[[LLM-Working/refactoring-plan/artifact-preview-contract]]` 为准。

## 关联笔记

- [[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]
- [[LLM-Working/refactoring-plan/next-release-realignment-roadmap]]
- [[LLM-Working/refactoring-plan/mode-baseline-spec]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- [[LLM-Working/refactoring-plan/contracts-to-current-ainrf-gap-plan]]
- [[LLM-Working/refactoring-plan/task-read-model-contract]]
- [[LLM-Working/refactoring-plan/workspace-session-container-summary-contract]]
- [[LLM-Working/refactoring-plan/artifact-preview-contract]]
- [[framework/v1-rfc]]
