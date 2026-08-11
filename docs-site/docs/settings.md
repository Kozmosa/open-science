---
title: 系统设置
description: 用户偏好、监控审计、Admin 用户管理、环境授权与技能仓库管理。
---

OpenScience 设置页面管理用户偏好、系统配置、用户与权限、环境授权、监控入口以及技能仓库。部分标签页仅管理员可见。

## SettingsPage

路由 `/settings`。设置页面以标签页形式组织：

| 标签 | 可见性 |
|------|--------|
| General | 所有用户 |
| Monitoring & Audit | 所有用户 |
| Users | 仅 Admin |
| Env Access | 仅 Admin |
| Collaborators | 所有用户 |

## General 标签

通用偏好设置，对所有登录用户可见：

- **默认起始页**（Default Route）：登录后的默认跳转页面，可选 Terminal / Tasks / Workspaces / Environments
- **终端字体大小**（Terminal Font Size）：控制 Xterm 终端的字号
- **编辑器字体大小**（Editor Font Size）：控制编辑器的字号（带上下限 clamp）
- **编辑器字体族**（Editor Font Family）：编辑器的字体选择
- **外观**（Appearance）：Light / Dark / System 主题与界面动画偏好
- **默认环境**（Default Environment）：文件浏览、终端与环境页面优先选择的运行环境
- **Project Defaults**：当前项目在浏览器中的默认环境选择

Task 的执行引擎、Researcher 类型和技能在正式的新建 Task 流程中显式选择，并由
Conversation/runtime contract 持久化。设置页不保存平行的浏览器本地执行 profile、
provider credentials 或每环境 Task 模板。

## Monitoring & Audit 标签

提供 Grafana、Prometheus 与 Litefuse 等已配置可观测性入口。未配置的服务不会显示为
可用链接。

## Users 标签（仅 Admin）

用户管理面板：

- 列出所有已注册用户（用户名、邮箱、角色和状态）
- 审批 `pending` 状态的用户
- 激活 / 禁用用户账户
- 重置用户密码

详见 [认证与授权](/auth)。

## Env Access 标签（仅 Admin）

环境授权管理：

- 为每个用户授予或撤销特定环境的访问权限
- 配置每个用户的 `max_concurrent_tasks` 上限
- `null` 表示不限制，`0` 表示暂停该用户在该环境启动新的外部 Task 执行

配额由 domain worker 在 Runtime Adapter 启动前原子预留。尚未跨入外调边界的
queued/claimed Task 会等待容量；`delivery_unknown` 仍可能对应已接受的外部调用，
因此在完成 reconciliation 前继续占用一个槽位。

## Collaborators 标签

项目协作者管理：

| 角色 | 权限 |
|------|------|
| `member`（读写） | 查看、创建和修改项目资源 |
| `viewer`（只读） | 仅可查看项目资源 |

支持添加新协作者和调整已有协作者的角色。

## Skill Registries

ARIS（OpenScience Research Intelligence System）技能仓库管理：

- 查看已安装的技能仓库源
- 安装新仓库（URL）
- 更新已有仓库的技能列表
- 浏览可用技能并安装到当前环境

## 相关文档

- [认证与授权](/auth) — 用户角色与权限详解
- [快速开始](/quickstart) — 首次启动与默认账户
