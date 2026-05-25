---
aliases:
  - 系统设置
  - Settings
  - settings
tags:
  - ainrf
  - settings
  - admin
  - users
  - env-access
  - collaborators
  - skill-registry
  - appearance
  - llm-provider
  - docs
  - obsidian-note
source_repo: scholar-agent
source_path: docs/ainrf/settings.md
last_local_commit: workspace aggregate
---

# 系统设置

> [!abstract]
> AINRF 设置页面管理用户偏好、系统配置、用户与权限、环境授权、LLM 提供商配置以及技能仓库。部分标签页仅管理员可见。

## SettingsPage

路由：`/settings`

设置页面以标签页形式组织：

- **General**：对所有用户开放
- **LLM Providers**：对所有用户开放
- **Users**、**Env Access**、**Collaborators**：仅对管理员角色可见

## General 标签

通用偏好设置，对所有登录用户可见：

- **默认起始页**（Default Route）：登录后的默认跳转页面，可选 Terminal / Tasks / Workspaces / Environments
- **终端字体大小**（Terminal Font Size）：控制 Xterm 终端的字号，支持动态调节
- **编辑器字体大小**（Editor Font Size）：控制编辑器的字号，支持动态调节（带上下限 clamp）
- **编辑器字体族**（Editor Font Family）：编辑器的字体选择
- **外观**（Appearance）：全局字体偏好，可选非衬线体（Sans-serif）或衬线体（Serif），通过 CSS Variable 全局生效
- **默认 Workspace**：任务的默认工作区路径
- **默认环境**（Default Environment）：任务执行的默认 target environment
- **Task Configuration**：任务执行引擎、Research Agent profile 和技能配置
- **Project Defaults**：每个环境下的任务模板默认值

### Task Configuration 中的 LLM Provider 快速填充

在 Task Configuration 的 Research Agent profile 编辑中，如果执行引擎为 `agent-sdk`，可以**从已配置的 LLM Provider 快速填充** API 配置：

- **Fill from provider** 下拉框列出所有在 LLM Providers 标签页中创建的 Provider
- 选择后自动回填 `apiBaseUrl`、`apiKey` 以及模型字段
- 填充后用户仍可手动修改任何字段
- profile 独立存储数据，后续修改 Provider 不影响已填充的 profile

## LLM Providers 标签

全局 LLM API 配置管理，集中存放不同格口的 API endpoint、认证和模型信息，供 agent profile 快速填充。

- **Provider 列表**：展示所有已创建的 LLM Provider，每行显示名称、格式（Anthropic / OpenAI badge）、Base URL
- **添加 Provider**：打开编辑对话框，Name 和 Base URL 为必填，API Key 可选
- **编辑 / 删除 Provider**：修改已有 provider 配置或删除（不影响已填充到 profile 的数据）
- **格式自适应表单**：
  - **Anthropic 格式**：显示 Opus Model / Sonnet Model / Haiku Model 三档模型输入框
  - **OpenAI 格式**：显示 Default Model 单行模型输入框
- **空状态提示**：无 provider 时引导用户添加第一个

## Users 标签（仅 Admin）

用户管理面板，仅 `admin` 角色可见：

- **用户列表**：列出所有已注册用户，显示用户名、邮箱、角色和状态
- **审批待定用户**：显示处于 `pending` 状态的用户，管理员可批准或拒绝
- **激活 / 禁用**：切换用户账户的启用状态
- **重置密码**：为指定用户生成密码重置令牌

详见 [[auth]]。

## Env Access 标签（仅 Admin）

环境授权管理，仅 `admin` 角色可见：

- **环境授权**：为每个用户授予或撤销特定环境的访问权限
- **并发任务配额**：配置每个用户的 `max_concurrent_tasks` 上限，限制用户在指定环境中的同时运行任务数

## Collaborators 标签

项目协作者管理：

- **协作者列表**：展示当前项目的所有协作者及其角色
- **角色**：
  - **member**（读写）：可以查看、创建和修改项目资源
  - **viewer**（只读）：仅可查看项目资源，无法创建或修改
- **添加 / 移除协作者**：支持添加新协作者和调整已有协作者的角色

## Skill Registries

ARIS（AINRF Research Intelligence System）技能仓库管理：

- **仓库列表**：查看已安装的技能仓库源
- **安装仓库**：添加新的技能仓库 URL
- **更新仓库**：刷新已安装仓库的技能列表
- **技能管理**：在仓库中浏览可用技能，查看详情并安装到当前环境

## 关联笔记

- [[auth]]
- [[index]]
