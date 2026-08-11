---
title: 工作区管理
description: Workspace 注册、Environment 绑定、Project 关联、执行可用性与文件浏览器。
---

OpenScience Workspace 是一个已登记的执行目录：它把某个 Environment、canonical path、owner 和可选 workspace context 组合成可授权、可关联到 Project 的领域对象。

Workspace 不是自动创建的本地目录模板。当前产品没有内置 `workspace-default`，也不会根据 label 自动生成 `default_workdir`。注册时必须明确选择 Environment、填写 canonical path 和 label；后端会在目标 Environment 上预检该路径。

## WebUI

Workspace 控制台位于 `/workspaces`，支持：

- 按 label、canonical path 或 Environment 搜索
- 只显示当前可执行的 Workspace
- 注册 Workspace，并可选立即关联到一个 Project、设为 primary Workspace
- 查看 owner、Environment、Task 数量、最近活动、Git 状态和 Project links
- owner 编辑 label、description、canonical path 和 workspace context
- 从 Workspace 直接打开文件浏览器、Terminal 或创建 Task
- unregister Workspace，而不是删除底层目录

Workspace 的 projection 状态为 `active` 或 `unregistered`。默认列表不返回 unregistered 记录；HTTP caller 可以显式使用 `include_unregistered=true` 读取历史 projection。

## Canonical HTTP Interface

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/domain/workspaces?include_unregistered=false` | 列出当前用户可见的 Workspace projection |
| POST | `/api/domain/workspaces` | 注册 Workspace；body 为 `environment_id`、`canonical_path`、`label` |
| GET | `/api/domain/workspaces/{workspace_id}` | 读取 Workspace、Environment、Project links 和执行可用性 |
| PATCH | `/api/domain/workspaces/{workspace_id}` | 更新 label、description、canonical path 或 workspace context |
| POST | `/api/domain/workspaces/{workspace_id}/unregister` | 将 Workspace 标记为 unregistered |
| POST / DELETE | `/api/domain/projects/{project_id}/workspaces/{workspace_id}` | 关联或解除 Project |
| PUT | `/api/domain/projects/{project_id}/primary-workspace/{workspace_id}` | 设置或替换 Project 的 primary Workspace |

所有 mutation 使用 `Idempotency-Key` header。PATCH transport 仍以 `default_workdir` 表示新的 canonical path、以 `workspace_prompt` 表示 workspace context；response 使用 `canonical_path` 和 `workspace_context`。Project 关联不能通过 Workspace PATCH 的 `project_id` 字段修改。

## Environment 与执行权限

每个 Workspace 只绑定一个 Environment，但可以关联多个 Project。Project link 单独记录 active/retired、primary 和当前用户能否执行；Project 不直接持有一组 Environment refs。

`can_execute` 是后端 projection，不是由 WebUI 猜测。执行、文件和 Terminal I/O 至少要求：

- Workspace、Project link 和 Environment identity 一致且处于可用状态
- 当前用户能看到相应领域对象
- 当前用户拥有该 Environment 的显式 active execution grant
- Workspace owner 与 Linux tenant execution identity 满足权限规则

可见但没有 execution grant 的 runtime I/O 返回 403；不可见资源返回 404。owner 或 admin 身份不会绕过显式 Environment grant。

## 文件浏览器

文件浏览器的 WebUI 路由是 `/workspace-browser`，不是 `/files`。从 Workspace 控制台打开时，URL 会携带 `environment_id` 和 `workspace_id`；可选 `path` 用于直接打开文件。

当前 WebUI 提供：

- 懒加载目录树和 Workspace 选择器
- 图片预览
- PDF authenticated stream 预览
- 文本文件的懒加载、只读 Monaco viewer，包含语法高亮和换行

对应的 canonical HTTP operations 是：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/files/list` | 列出目录；query 包含 `environment_id`、`path` 和可选 `workspace_id` |
| GET | `/api/files/read` | 读取用于 WebUI 预览的文件内容 |
| GET | `/api/files/stream` | 流式读取 PDF 等文件 |
| POST | `/api/files/upload` | 授权 caller 的文件上传 operation；当前 FileBrowserPage 未暴露上传控件 |

普通 read 上限为 50,000,000 bytes；stream 的上限为 100 MiB，upload route 也有 100 MiB 硬上限，但部署级请求体限制可能更低（默认 50 MiB）。超限请求返回 413。目录列表最多返回 1,000 项。

所有 file operation 都会在实际 I/O 前重新校验 Environment execution grant 与可选 Workspace owner，并对敏感路径访问写入统一审计 telemetry。

## 与 Task 和 Terminal 的关系

创建 Task 时选择的是与目标 Project 保持 active link 的可执行 Workspace。Task 的 Environment 从该 Workspace 派生；worker 在 Runtime Adapter 外调前仍会重新校验 Environment grant、容量和 Workspace path。

Terminal 页面位于 `/terminal`，按 Environment 创建或读取 session。Workspace canonical path 是任务和文件操作的目录上下文，但不是一个可以替代 Environment grant 的授权凭据。

## 相关文档

- [项目管理](/projects) — Project–Workspace link、primary Workspace 与 Task 关系图
- [终端管理](/terminal) — Environment terminal 与 attachment session
- [安全](/security/) — 权限、请求限制与审计边界
