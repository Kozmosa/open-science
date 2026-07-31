---
title: 运行记录
description: Task 与 TaskAttempt 执行历史、项目用量和 Runs 页面功能。
---

运行记录以正式 Task 为主体，展示每个 Task 的当前状态、详情和 TaskAttempt 执行历史。OpenScience 不再把 Task 重新包装成独立 Session 资源。

## HTTP Interface

- `GET /api/tasks`：Task 列表，可使用 `project_id`、`include_archived`、`limit` 和 `sort` 筛选。
- `GET /api/tasks/{task_id}`：Task 详情。
- `GET /api/tasks/{task_id}/attempts`：TaskAttempt 执行历史。
- `GET /api/domain/projects/{project_id}/usage-summary`：项目 Task、Attempt、时长、Token 和成本汇总。

Task 创建、Retry 和 Fork 都返回统一的 `{ task, attempt, dispatch }` mutation 结果。前端 Adapter 解包该结果，页面不直接消费原始 transport payload。

## Runs 页面

WebUI 通过 `/runs` 访问运行记录：

- 左侧列出 Task，可按标题或 prompt 搜索；
- 右侧显示所选 Task 的 Project、Workspace、Environment、执行命令和结果；
- TaskAttempt 按序展示状态、耗时、Token 与模型成本；
- Project usage summary 显示项目级 Task、Attempt、Token 和成本统计。

## 与 Timeline 的关系

Runs 用于查看单个 Task 及其执行历史；Timeline 使用同一 Task / TaskAttempt 投影进行跨项目时间分布展示。两者都不依赖 Session 兼容投影。

## 相关文档

- [WebUI](/webui)
- [项目管理](/projects)
- [时间线](/timeline)
