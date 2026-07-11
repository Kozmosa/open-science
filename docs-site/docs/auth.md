---
title: 认证与授权
description: JWT Bearer Token 认证、用户角色（admin/member）、注册审批、环境授权与项目协作者管理。
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
| POST | `/auth/register` | 注册（状态为 `pending`） |
| POST | `/auth/login` | 登录，返回 access + refresh |
| POST | `/auth/refresh` | 使用 refresh token 刷新访问令牌 |
| POST | `/auth/logout` | 登出（删除 refresh token） |
| GET | `/auth/me` | 获取当前用户信息 |
| POST | `/auth/change-password` | 修改密码 |

### 注册

```json
POST /auth/register
{
  "username": "user1",
  "display_name": "用户一",
  "password": "secure-password"
}
```

- `username`：仅允许 ASCII 字母、数字、点（`.`）、下划线（`_`）、连字符（`-`），1-64 字符
- `display_name`：任意 Unicode，1-128 字符，用于 WebUI 显示
- `password`：最少 4 字符

返回 `201` 表示注册成功，状态为 `pending`，等待管理员审批。

### 登录

```json
POST /auth/login
{
  "username": "user1",
  "password": "secure-password"
}
```

返回 access token、refresh token 和用户信息。`pending` 和 `disabled` 状态的用户无法登录。

## 用户角色

| 角色 | 权限范围 |
|------|---------|
| `admin` | 全部权限：用户管理、环境授权、项目管理、所有任务 |
| `member` | 自有资源 + 协作项目资源，访问已被授权的环境 |

## 用户状态

```
pending → active / disabled
```

- **pending**：新注册用户，等待管理员审批
- **active**：正常可用
- **disabled**：已被管理员禁用，无法登录

## 首次 Admin 创建

服务首次启动（`openscience serve`）时，若数据库中无用户，自动创建初始管理员：

- 用户名：`admin` / 密码：`admin`
- 标记 `must_change_password = true`
- 自动激活并授予 `localhost` 环境权限

首次登录 `/auth/me` 返回 `must_change_password: true`，前端引导用户修改密码。

## Admin 面板

管理员通过 `require_admin` 中间件保护的后台接口管理系统：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/users` | 列出所有用户 |
| PATCH | `/admin/users/{user_id}` | 激活/禁用用户 |
| PUT | `/admin/users/{user_id}/password` | 重置用户密码 |
| PUT | `/admin/environments/{env_id}/access` | 授予环境访问权限 |
| DELETE | `/admin/environments/{env_id}/access/{user_id}` | 撤销环境访问权限 |

管理员可以：审批 `pending` 用户、禁用/启用用户、重置密码、授予或撤销环境访问、设置并发任务配额。

## 环境授权

每个用户可以独立授权访问不同环境，并限制并发任务数：

```json
PUT /admin/environments/env-localhost/access
{
  "user_id": "abc123",
  "max_concurrent_tasks": 3
}
```

## 项目协作者

项目所有者可以添加协作者：

| 角色 | 权限 |
|------|------|
| `member` | 完全协作权限 |
| `viewer` | 只读权限 |

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/{project_id}/collaborators` | 查看协作者 |
| PUT | `/projects/{project_id}/collaborators` | 添加协作者 |
| DELETE | `/projects/{project_id}/collaborators/{user_id}` | 移除协作者 |

## CLI 登录

```bash
openscience login --server http://localhost:8000
```

交互式输入用户名和密码，成功后缓存 token 到本地文件，后续 API 请求自动携带 Authorization 头。

## 相关文档

- [系统设置](/settings) — Admin 管理面板
- [快速开始](/quickstart) — 首次启动与默认账户
