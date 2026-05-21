---
aliases: [AINRF 使用文档, AINRF Usage Guide]
tags: [ainrf, docs, index]
source_repo: scholar-agent
---

# AINRF 使用文档

> [!abstract]
> AINRF 是 scholar-agent 的核心前后端产品，提供 CLI、REST API、WebUI、Terminal、
> Workspace Browser、任务引擎、多用户鉴权、性能监控等完整能力。本目录是用户文档入口。

## 核心子系统

| 子系统 | 说明 | 文档 |
|--------|------|------|
| 快速开始 | 安装、初始化、首次启动 | [[quickstart]] |
| CLI | 命令行工具参考 | [[cli]] |
| WebUI | 前端页面与布局 | [[webui]] |
| 认证 | JWT 鉴权、用户角色、Admin 面板 | [[auth]] |
| 项目管理 | Canvas DAG 可视化、任务创建与连线 | [[projects]] |
| 终端 | Personal/Agent 会话、本地 bash、远程 SSH | [[terminal]] |
| 工作区 | Workspace 管理、文件浏览器、Monaco 编辑器 | [[workspace]] |
| 会话追踪 | Session/Attempt 链、成本与耗时统计 | [[sessions]] |
| 时间线 | Gantt 图、任务时间分布可视化 | [[timeline]] |
| 资源监控 | GPU/CPU/内存、进程树、环境检测 | [[resources]] |
| 设置面板 | 通用设置、Admin 用户管理、环境授权 | [[settings]] |
| 开发命令 | 测试、构建、lint、性能审计 | [[development]] |

## 关联笔记

- [[index]]
- 设计规范：`docs/superpowers/specs/`
- 实施计划：`docs/superpowers/plans/`
- 历史文档：`docs/archive/`
