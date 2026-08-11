---
title: 认证与授权
description: JWT Bearer Token 认证、用户角色（admin/member）、注册审批、Environment execution grant 与 Project 成员管理。
---

OpenScience 使用 JWT Bearer Token 认证机制，支持用户注册审批、角色权限、环境授权与项目协作。

## JWT 令牌

认证使用 HS256 签名的 JWT 令牌：

- **Access Token**：15 分钟有效期，携带 `sub`（用户 ID）、`username`、`role` 声明
- **Refresh Token**：7 天有效期，以 SHA256 哈希存储在 SQLite 中（`refresh_tokens` 表）
- 密钥来源优先级：环境变量 `AINRF_JWT_SECRET` > `~/.ainrf/jwt_secret` 文件 > 自动生成

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 注册（状态为 `pending`） |
| POST | `/api/auth/login` | 登录，返回 access + refresh |
| POST | `/api/auth/refresh` | 使用 refresh token 刷新访问令牌 |
| POST | `/api/auth/logout` | 登出（删除 refresh token） |
| GET | `/api/auth/me` | 获取当前用户信息 |
| POST | `/api/auth/change-password` | 修改密码 |

### 注册

```json
POST /api/auth/register
{
  "username": "user1",
  "display_name": "用户一",
  "password": "secure-password"
}
```

- `username`：2–31 字符；首位必须是小写 ASCII 字母或数字，其余仅允许小写字母、数字、下划线（`_`）和连字符（`-`）
- `display_name`：任意 Unicode，1-128 字符，用于 WebUI 显示
- `password`：最少 4 字符

返回 `201` 表示注册成功，状态为 `pending`，等待管理员审批。

### 登录

```json
POST /api/auth/login
{
  "username": "user1",
  "password": "secure-password"
}
```

返回 access token、refresh token 和用户信息。`pending` 和 `disabled` 状态的用户无法登录。

## 用户角色

| 角色 | 权限范围 |
|------|---------|
| `admin` | 用户与 Environment grant 管理、全局 registry 可见性及 Project 管理；不自动获得 runtime execution 或 Project publish 能力 |
| `member` | 自有资源与显式加入的 Project；runtime execution 仍要求对应 Environment 的 active grant |

## 用户状态

```
pending → active / disabled
```

- **pending**：新注册用户，等待管理员审批
- **active**：正常可用
- **disabled**：已被管理员禁用，无法登录

## 首次 Admin 创建

服务首次启动（`openscience serve`）时，若数据库中无用户，自动创建初始管理员：

- 用户名：`admin`
- 密码：随机生成的 24 字符密码，写入 `<state_root>/admin_initial_password.txt`
- 密码文件权限：`0600`
- 标记 `must_change_password = true`
- 自动激活并为 `env-localhost` 写入一条显式 seed execution grant

首次登录后，`GET /api/auth/me` 返回 `must_change_password: true`，前端引导用户修改密码。
seed grant 与管理员角色是两个不同的授权事实；若该 grant 被撤销，管理员也不能绕过它执行 runtime I/O 或启动 Task delivery。

## Admin 面板

管理员通过 `require_admin` 中间件保护的后台接口管理系统：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/users` | 列出所有用户 |
| PATCH | `/api/admin/users/{user_id}` | 激活/禁用用户 |
| PUT | `/api/admin/users/{user_id}/password` | 重置用户密码 |
| GET | `/api/admin/environments/{env_id}/access` | 列出 Environment 的 active grants |
| PUT | `/api/admin/environments/{env_id}/access` | 授予或更新 Environment execution grant |
| DELETE | `/api/admin/environments/{env_id}/access/{user_id}` | 撤销 Environment execution grant |

管理员可以：审批 `pending` 用户、禁用/启用用户、重置密码、授予或撤销环境访问、设置并发任务配额。

## 环境授权

管理员可以为每个用户管理不同 Environment 的显式 execution grant，并限制并发任务数：

```json
PUT /api/admin/environments/env-localhost/access
{
  "user_id": "abc123",
  "max_concurrent_tasks": 3
}
```

该上限按“用户 + 环境”统计已经进入外部 delivery 的不同 Task。`null` 表示不限，
`0` 表示不允许新的外部执行启动；queued/claimed submission 可以继续持久等待。
为防止重复外调，acceptance 尚不确定的 `delivery_unknown` Task 在 reconciliation
完成前仍计入并发槽。

Environment registry 可见性不是 execution grant。runtime file/terminal I/O 与 Task
delivery 都会重新校验 explicit active grant；可见但无 grant 返回 403，不可见返回
404。owner 与 admin 身份均不能绕过这项检查。

## 项目协作者

Project owner 或 admin 可以添加、更新和移除成员：

| 角色 | 权限 |
|------|------|
| `editor` | 可编辑 Project 资源；仅当 `can_publish=true` 时可发布 Project Context |
| `viewer` | 只读权限 |

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/domain/projects/{project_id}/members` | 查看成员 |
| PUT | `/api/domain/projects/{project_id}/members/{member_user_id}` | 添加或更新成员的 `role` 与 `can_publish` |
| DELETE | `/api/domain/projects/{project_id}/members/{member_user_id}` | 移除成员 |

`can_publish=true` 只允许与 `role="editor"` 一起使用。全局 admin 可以管理成员，
但不会仅凭 admin 角色获得 Project publish 能力；发布仍要求实际 Project owner 或
带 `can_publish` 的 editor membership。

## CLI 登录

```bash
openscience login --server http://localhost:8000
```

交互式输入用户名和密码，成功后缓存 token 到本地文件，后续 API 请求自动携带 Authorization 头。

## 相关文档

- [系统设置](/settings) — Admin 管理面板
- [快速开始](/quickstart) — 首次启动与默认账户
