---
aliases:
  - Contracts to Current AINRF Gap Plan
  - Contract 到当前 AINRF 的缺口规划
tags:
  - scholar-agent
  - gap-analysis
  - contract
  - implementation-plan
source_repo: scholar-agent
source_path: /Users/kozmosa/code/scholar-agent
last_local_commit: workspace aggregate
---
# Contract 到当前 AINRF 的缺口规划

> [!abstract]
> 本文档用于把 `refactoring-plan/` 下已经冻结的 contracts，与当前 `src/ainrf/` 已有实现逐项对照，明确“哪些已经具备、哪些只具备一半、哪些仍然缺失”，并给出 next release 最小实现切片顺序。目标不是重新设计系统，而是把规划链真正转换成可执行的工程缺口图。

> [!warning]
> 本文档成稿于 `task_harness / workspaces / terminal / code_server` 成为当前产品面主线之前。文中出现的 `src/ainrf/events/`、`src/ainrf/gates/`、`TaskArtifactsResponse` 等表述，应按当时的 gap-analysis 语境理解，而不是当作当前源码树的现状描述。当前 source of truth 请优先回到 [[ainrf/index]]、`src/ainrf/README.md` 与 [[superpowers/specs/2026-04-22-implemented-runtime-surface-archive]]。

## 结论

- 本文成稿时，把 FastAPI、task API、health、gates、events、state store、SSH health 视为 next release control plane 的骨架。
- 当前仓库已经进一步收敛为 `task_harness + tasks + workspaces + terminal + environments + code_server` 的控制面，文中的旧模块名不再代表现状目录。
- 本文保留价值主要在于“dashboard-oriented summary / preview / aggregation” 这组缺口判断，而不是它对当时模块边界的逐字枚举。

## 对照范围

本次对照的 contracts 包括：

- `[[LLM-Working/refactoring-plan/task-read-model-contract]]`
- `[[LLM-Working/refactoring-plan/workspace-session-container-summary-contract]]`
- `[[LLM-Working/refactoring-plan/artifact-preview-contract]]`

本文当时对照的实现主要来自：

- `src/ainrf/api/routes/tasks.py`
- `src/ainrf/api/routes/health.py`
- `src/ainrf/api/schemas.py`
- `src/ainrf/state/`
- `src/ainrf/events/`
- `src/ainrf/gates/`

其中 `src/ainrf/events/` 与 `src/ainrf/gates/` 已不在当前源码树中。

## 一、Task Read Model 合约对照

### 当时已具备

- `TaskSummaryResponse` 已提供：
  - `task_id`
  - `mode`
  - `status`
  - `created_at`
  - `updated_at`
  - `current_stage`
  - `termination_reason`
- `TaskDetailResponse` 已额外提供：
  - `budget_limit`
  - `budget_used`
  - `gates`
  - `active_gate`
  - `artifact_summary`
  - `config`

### 当时只具备一半

- `input_summary`
  - 当时只有原始 `config`，没有面向 dashboard 的 `title` / `brief` / `seed_inputs` / `target_inputs` 摘要层。
- `progress_summary`
  - 当时只有 `current_stage` 和事件流能力，没有正式的 `current_checkpoint`、`milestones`、`recent_events` 聚合字段。
- `result_summary`
  - 当时只有 `termination_reason` 和 artifact summary，没有 `result_brief`、`recent_artifacts`、`error_summary` 的专门摘要层。

### 当时缺失

- dashboard 友好的 task card shape。
- 首页任务列表与详情页之间明确分层的 read model。
- 轻量 summary 字段与原始 config/payload 之间的边界。

### 工程判断

- 这部分不需要推翻 `TaskRecord`。
- 更合理的做法是在现有 API schema 之上增加一层 dashboard-oriented summary shape，而不是让前端直接消费原始 `config`。

## 二、Workspace / Session / Container Summary 合约对照

### 当时已具备

- `TaskCreateRequest.container` 已有：
  - `host`
  - `port`
  - `user`
  - `ssh_key_path`
  - `project_dir`
- `/health` 已能提供：
  - `container_configured`
  - `ssh_ok`
  - `claude_ok`
  - `anthropic_api_key_ok`
  - `project_dir_writable`
  - `gpu_models`
  - `cuda_version`
  - `disk_free_bytes`

### 当时只具备一半

- workspace summary
  - 当时有 `project_dir`，但没有专门的 `workspace_id` / `workspace_label` 抽象。
- session summary
  - 当时能从健康检查和 SSH 可达性间接推断 session 可用性，但没有正式的 `session_status` / `connected` / `recoverable` read model。
- resource snapshot
  - 当时只在 `/health` 里有部分 container health 字段，没有统一成 dashboard summary shape。

### 当时缺失

- 一个稳定的 task-scoped execution context summary。
- 能直接挂在 task detail 上的 workspace/session/container 摘要响应。
- 统一的 `resource_snapshot` 结构。

### 工程判断

- 这部分很适合先做“只读摘要层”，不需要先做真正的 workspace/session runtime 重构。
- next release 只需要 summary contract，不需要正式引入独立 infra domain model。

## 三、Artifact Preview 合约对照

### 当时已具备

- `TaskArtifactsResponse` 已支持列出 task 关联 artifacts。
- `ArtifactItemResponse` 已有：
  - `artifact_id`
  - `artifact_type`
  - `source_task_id`
  - `summary`
  - `status`
  - `payload`

### 当时只具备一半

- 已有 artifact list，但没有 dashboard-friendly preview metadata。
- 当时的 `payload` 是原始 JSON payload，不等于 preview contract 所需的：
  - `display_title`
  - `preview_format`
  - `preview_ref`

### 当时缺失

- 三类核心 artifact 的稳定 preview shape：
  - tables
  - reports
  - figures
- recent artifacts 轻量入口 shape。
- artifact list 和 artifact preview 之间的清晰分层。

### 工程判断

- 这里最关键的不是“支持所有 artifact”，而是先为结果导向的三类 artifact 增加 preview metadata。
- next release 应避免让前端直接解析原始 artifact payload 来猜预览方式。

## 四、总体缺口总结

### 当时已有骨架

- task API 已有。
- health API 已有。
- event stream 已有。
- gate lifecycle 已有。
- artifact list 已有。

### 当时判断的真实缺口

1. 缺 dashboard-oriented read model，而不是缺 task 概念。
2. 缺 execution context summary，而不是缺 SSH / container 基础。
3. 缺 preview metadata，而不是缺 artifact list。

### 不应误判为短期目标的内容

- 完整 experiment runtime。
- 全局 analytics。
- 多用户 / 多工作区平台化。
- 完整 token telemetry 系统。

## 五、推荐实现切片

### Slice 1：Task Summary Layer

目标：

- 在现有 `TaskSummaryResponse` / `TaskDetailResponse` 之上，为 dashboard 增加 summary-oriented 字段分层。

最小交付：

- `title`
- `brief`
- `current_checkpoint`
- `recent_events`
- `result_brief`

### Slice 2：Execution Context Summary Layer

目标：

- 为 task detail 增加 workspace / session / container / resource snapshot 摘要。

最小交付：

- `workspace_label`
- `project_dir`
- `session_status`
- `ssh_available`
- `resource_snapshot`

### Slice 3：Artifact Preview Metadata Layer

目标：

- 为三类核心 artifact 加上 dashboard 直接可用的 preview metadata。

最小交付：

- `display_title`
- `preview_format`
- `preview_ref`

### Slice 4：Recent Artifacts / Recent Tasks 聚合层

目标：

- 为首页提供轻量聚合接口或可复用响应 shape。

最小交付：

- recent finished tasks
- recent artifacts
- running task summary

## 六、当前最推荐的实施顺序

1. 先做 task read model summary layer。
2. 再做 artifact preview metadata。
3. 再做 workspace / session / container summary。
4. 最后评估是否值得引入 token telemetry 候选字段。

原因：

- task 和 artifact preview 对 dashboard 首屏价值最高。
- workspace / session / container 适合在已有 health 基础上逐步补。
- token telemetry 仍然是最容易引发 scope 膨胀的部分。

## 七、后续文档回写要求

- roadmap 应把上述 4 个 slices 转成原子实施任务。
- architecture baseline 应把这些 gap 映射到具体模块边界。
- 如果后续开始改代码，`impl` 文档应按 slice 记录，而不是跳过 gap analysis 直接堆功能。

## 关联笔记

- [[LLM-Working/refactoring-plan/index]]
- [[LLM-Working/refactoring-plan/architecture-baseline-plan]]
- [[LLM-Working/refactoring-plan/task-read-model-contract]]
- [[LLM-Working/refactoring-plan/workspace-session-container-summary-contract]]
- [[LLM-Working/refactoring-plan/artifact-preview-contract]]
- [[ainrf/index]]
