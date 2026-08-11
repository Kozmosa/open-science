---
title: 项目管理
description: Project 生命周期、Workspace 关联、Task 视图、显式关系图与项目上下文。
---

OpenScience 以项目（Project）组织研究任务、Workspace 关联、成员权限和项目上下文。Project 本身不直接保存 Environment 引用；任务的执行 Environment 来自所选 Workspace。

## WebUI

项目控制台位于 `/projects`。页面提供：

- 创建、搜索和切换 Project
- 查看 active 或 archived 生命周期状态
- Overview、Tasks、Workspaces、Context、Settings 五个视图
- 关联或解除 Workspace，并为 Project 设置一个 primary Workspace
- 按当前用户权限创建 Task、编辑 Project、管理成员或归档 Project

Project 可以关联多个 Workspace。primary Workspace 是该 Project 的首选执行上下文，但创建 Task 时仍会校验 Workspace 是否 active、是否关联到当前 Project，以及当前用户是否具备执行能力。

## Canonical HTTP Interface

WebUI 路由与后端 HTTP 路径是两个不同的 Interface。Project 的 canonical product HTTP prefix 是 `/api`，核心操作如下：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/domain/projects?include_archived=false` | 列出当前用户可见的 Project projection |
| POST | `/api/domain/projects` | 创建 Project；body 包含 `name` 和可选 `description` |
| GET | `/api/domain/projects/{project_id}` | 读取 Project projection、权限和 primary Workspace |
| PATCH | `/api/domain/projects/{project_id}` | 只更新 `name` 或 `description` |
| POST | `/api/domain/projects/{project_id}/archive` | 归档 Project |
| POST | `/api/domain/projects/{project_id}/unarchive` | 恢复 Project |
| POST / DELETE | `/api/domain/projects/{project_id}/workspaces/{workspace_id}` | 关联或解除 Workspace |
| PUT | `/api/domain/projects/{project_id}/primary-workspace/{workspace_id}` | 设置或替换 primary Workspace |
| GET | `/api/domain/projects/{project_id}/members` | 列出 Project 成员 |
| PUT / DELETE | `/api/domain/projects/{project_id}/members/{member_user_id}` | 添加、更新或移除成员 |

所有 Project mutation 使用 `Idempotency-Key` header。Workspace 选择不能混入 Project PATCH；它由专门的 Project–Workspace Interface 管理。

## Tasks 视图

Tasks 视图支持列表和关系图两种呈现。Task 状态来自 Conversation projection，当前 transport union 为：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `completed`

点击 Task 会进入 `/tasks?task={task_id}`。具有相应权限的用户也可以把 Task 移动到另一个 active Project；移动会重新固定目标 Project 的当前 Context Version。

## 显式 Task 关系图

关系图使用 React Flow、Controls、MiniMap 和 dagre 初始布局。图中只展示后端已经持久化的 Task relationship，不会根据创建时间自动生成或持久化线性关系。

具有编辑权限的用户可以：

1. 从 source Task 拖线到 target Task。
2. 通过 `/api/domain/projects/{project_id}/task-relationships` 创建显式关系。
3. 删除已有关系；失败时 WebUI 会恢复原来的边。

Fork 等领域操作可以产生带 `derived_from` 等 relationship type 的边；手动连线使用后端的 canonical relationship 记录。

节点位置保存在浏览器 `localStorage` 的 `openscience:project-layout:{projectId}`。Reset Layout 会清除该 Project 的保存位置并重新运行 dagre；旧 `ainrf:project-layout:{projectId}` 仅作为一次性读取迁移来源。

## 创建 Task

Task 创建对话框使用 Conversation Module 的正式 Task Interface。普通创建流程包含：

| 字段 | 说明 |
| --- | --- |
| Project | 目标 active Project；需要 `can_create_task` 权限 |
| Workspace | 必须 active、可执行并与所选 Project 保持 active link |
| Environment | 从 Workspace projection 派生，只读展示 |
| Task preset | 同时选择一组 researcher / engine 默认值 |
| Execution engine | `claude-code`、`agent-sdk` 或 `codex-app-server` |
| Researcher type | `vanilla` 或 `aris-researcher` |
| Title | 可选标题 |
| Prompt | 普通 Task 的必填研究输入 |
| Skills | 仅 `vanilla` researcher 可选择；运行时按正式 skill registry 解析 |

Task 不再使用旧的 JSON “任务配置”或 Python runtime 选择器。最终执行仍会在 Conversation admission 和 worker Adapter seam 再次校验 Workspace、Environment grant、容量与 runtime preflight。

## Project Context 与成员

Context 视图维护 draft、发布后的 immutable Context Version、历史 diff 和候选片段。新建或移动 Task 时会固定当时的 active Context Version，而不是在执行期间读取可变草稿。

Settings 视图维护 Project 名称、描述和成员。成员角色为 viewer 或 editor；owner/admin projection 由领域权限 Module 计算。是否能编辑、发布、管理成员、归档或创建 Task，以 Project response 中的 `permissions` 为准。

## 相关文档

- [工作区](/workspace) — Workspace 注册、Project 关联与文件浏览
- [终端管理](/terminal) — Environment terminal session
- [运行记录](/runs) — Task、Turn 与 Item 执行历史
