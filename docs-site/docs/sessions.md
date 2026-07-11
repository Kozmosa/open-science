---
title: 会话追踪
description: Session 与 Attempt 链式结构、成本追踪、SessionsPage 页面功能。
---

会话（Session）是 OpenScience 中一次用户交互任务的容器，将多次执行尝试（Attempt）组织为可追溯的链，并聚合成本与耗时统计。

## Session

Session 表示一次用户交互会话，关联一个项目（Project），作为 Attempt 的容器：

| 字段 | 说明 |
|------|------|
| `id` | 主键 |
| `project_id` | 所属项目 |
| `title` | 会话标题 |
| `status` | `active` / `completed` / `archived` |
| `task_count` | 关联任务数量 |
| `total_duration_ms` | 总耗时（毫秒） |
| `total_cost_usd` | 总成本（USD） |

### Session 状态

```
active → completed
active → archived
```

## Attempt

Attempt 是 Session 内的单次执行尝试，通过 `parent_attempt_id` 形成 attempt 链，支持中断后继续：

| 字段 | 说明 |
|------|------|
| `id` | 主键 |
| `session_id` | 所属 session |
| `task_id` | 关联任务（nullable） |
| `parent_attempt_id` | 父 attempt，形成链式结构 |
| `attempt_seq` | 序号（1, 2, 3...） |
| `intervention_reason` | 中断/继续原因 |
| `status` | `running` / `completed` / `failed` / `interrupted` |

### Attempt 状态

```
running → completed
running → failed
running → interrupted → (下一 attempt)
```

Attempt 的生命周期由 Task Harness 自动维护：task 从 QUEUED 转为 STARTING 时自动创建 Attempt，task 完成/失败时自动更新对应 Attempt 的状态、耗时和用量数据。

## 成本追踪

Session 表预聚合 `total_cost_usd`（USD 计费）和 `total_duration_ms`（毫秒耗时）两个字段，避免列表页每次查询时实时 JOIN 计算。每次 Attempt 完成后自动 recalculate。

## SessionsPage

WebUI 中通过路由 `/sessions` 访问，提供：

- **Session 列表**：左侧面板列出所有 session，显示标题、状态、创建时间
- **Session 详情**：右侧展示 session 下的 Attempt 链，按 seq 排序
- **筛选**：支持按 `project_id` 和 `status` 参数过滤
- **时间排序**：列表按创建时间倒序排列

Attempt 链以垂直时间线展示，每个 attempt 卡片显示序号、状态标记、关联任务（可点击跳转）、耗时和中断原因。

## 与 Task 的关联

Task 创建时可绑定 `session_id`，使该 task 的 attempt 自动归入对应 session。Task 详情页中显示所属 session 的链接，TaskCreateForm 提供可选的 session 选择器。

## 相关文档

- [项目管理](/projects) — 项目与任务管理
- [时间线](/timeline) — Gantt 图时间分布可视化
