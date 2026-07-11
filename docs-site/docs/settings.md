---
title: 系统设置
description: 用户偏好、LLM Provider 配置、Admin 用户管理、环境授权与技能仓库管理。
---

OpenScience 设置页面管理用户偏好、系统配置、用户与权限、环境授权、LLM 提供商配置以及技能仓库。部分标签页仅管理员可见。

## SettingsPage

路由 `/settings`。设置页面以标签页形式组织：

| 标签 | 可见性 |
|------|--------|
| General | 所有用户 |
| LLM Providers | 所有用户 |
| Users | 仅 Admin |
| Env Access | 仅 Admin |
| Collaborators | 所有用户 |

## General 标签

通用偏好设置，对所有登录用户可见：

- **默认起始页**（Default Route）：登录后的默认跳转页面，可选 Terminal / Tasks / Workspaces / Environments
- **终端字体大小**（Terminal Font Size）：控制 Xterm 终端的字号
- **编辑器字体大小**（Editor Font Size）：控制编辑器的字号（带上下限 clamp）
- **编辑器字体族**（Editor Font Family）：编辑器的字体选择
- **外观**（Appearance）：Sans-serif 或 Serif，通过 CSS Variable 全局生效
- **默认 Workspace**：任务的默认工作区路径
- **默认环境**（Default Environment）：任务执行的默认 target environment
- **Task Configuration**：任务执行引擎、Research Agent profile 和技能配置
- **Project Defaults**：每个环境下的任务模板默认值

### LLM Provider 快速填充

在 Task Configuration 的 Research Agent profile 编辑中，如果执行引擎为 `agent-sdk`，可以从已配置的 LLM Provider 快速填充 API 配置：

1. **Fill from provider** 下拉框列出所有已创建的 Provider
2. 选择后自动回填 `apiBaseUrl`、`apiKey` 以及模型字段
3. 填充后用户仍可手动修改任何字段
4. profile 独立存储数据，后续修改 Provider 不影响已填充的 profile

## LLM Providers 标签

全局 LLM API 配置管理，集中存放不同提供商的 API endpoint、认证和模型信息：

- **Provider 列表**：每行显示名称、格式（Anthropic / OpenAI badge）、Base URL
- **添加 / 编辑 / 删除 Provider**：Name 和 Base URL 必填，API Key 可选
- **格式自适应表单**：
  - **Anthropic 格式**：显示 Opus / Sonnet / Haiku 三档模型输入框
  - **OpenAI 格式**：显示 Default Model 单行输入框
- **空状态提示**：无 provider 时引导用户添加

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
