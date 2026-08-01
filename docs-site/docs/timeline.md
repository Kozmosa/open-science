---
title: 时间线
description: Gantt 图可视化 Task 运行的时间分布，展示 Turn 持续时间、状态和成本。
---

时间线（Timeline）以 Gantt 图形式可视化 Task 运行的时间分布，展示每次尝试的持续时间、状态和成本，支持跨项目筛选。

## Gantt 图

Timeline 页面的核心是一个纯前端的 Gantt 图表，数据来自 `GET /api/tasks` 和 `GET /api/tasks/{task_id}/turns`：

- **左侧标签**：每个 Task 显示为一行，包含标题和 Turn 摘要
- **右侧时间轴**：每个 Turn 作为一个百分比定位的色块，宽度对应执行时长
- **交互**：hover 显示 Turn 详情（序号、状态、耗时、成本、中断原因），点击跳转到关联任务

### 定位算法

```
left  = (turnStart - minTime) / span * 100
width = max(1, (turnEnd - turnStart) / span * 100)
```

### 自适应时间轴

| 时间跨度 | 刻度单位 |
|---------|---------|
| ≤ 24 小时 | 小时刻度 |
| ≤ 7 天 | 天刻度 |
| > 7 天 | 周刻度 |

## 颜色编码

| 状态 | 颜色 | 含义 |
|------|------|------|
| `queued` | 灰色 | 等待执行 |
| `starting` | 蓝色 | 正在启动 |
| `running` | 绿色 | 执行中 |
| `completed` | 深绿色 | 成功完成 |
| `failed` | 红色 | 执行失败 |
| `interrupted` | 琥珀色 | 被中断 |

## 页面控件

路由 `/timeline`，包含：

- **TimelineControls**：项目选择器、日期范围选择、快速预设（今天 / 过去 7 天 / 过去 30 天）、统计摘要
- **GanttChart**：核心图表组件，包含时间轴表头和逐行渲染的 Gantt 行

轮询间隔：Task 列表 15 秒、Turn 详情 30 秒。

## 使用场景

- 对比不同 project 的任务执行模式
- 追踪中断重试的历史链条
- 快速识别执行时间异常的任务

## 相关文档

- [项目管理](/projects) — 项目与任务管理
- [运行记录](/runs) — Task 与 Turn/Item 执行历史
