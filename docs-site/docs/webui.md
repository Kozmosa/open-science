---
title: WebUI 总览
description: OpenScience 前端页面架构、路由表、技术栈与布局结构。
---

## 启动方式

```bash
scripts/webui.sh dev     # 开发模式（Vite HMR，端口 5173）
scripts/webui.sh         # 预览模式（构建后，端口 4173）
```

## 技术栈

| 技术 | 用途 |
|------|------|
| React 19 | UI 框架 |
| TypeScript | 类型安全 |
| Vite 8 | 构建工具 |
| Tailwind CSS v4 | 样式系统 |
| TanStack React Query v5 | 状态管理与数据请求 |
| @xyflow/react v12 | 项目 Canvas（ReactFlow） |
| xterm.js | 终端模拟器 |
| Monaco Editor | 代码编辑器（懒加载） |

## 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | LoginPage | 登录 |
| `/register` | RegisterPage | 注册（新账户需 admin 审批） |
| `/change-password` | ChangePasswordPage | 修改密码 |
| `/projects` | ProjectsPage | 项目 Canvas + 任务管理 |
| `/tasks` | TasksPage | 任务列表与详情 |
| `/terminal` | TerminalPage | 终端会话 |
| `/workspace-browser` | FileBrowserPage | 文件浏览器 |
| `/sessions` | SessionsPage | 会话追踪 |
| `/timeline` | TimelinePage | 时间线（Gantt 图） |
| `/resources` | ResourcesPage | 资源监控（GPU/CPU/内存） |
| `/environments` | EnvironmentsPage | 环境管理 |
| `/workspaces` | WorkspacesPage | 工作区管理 |
| `/settings` | SettingsPage | 设置面板 |

## 布局结构

- **左侧可折叠侧边栏**：导航菜单 + 用户信息 + 登出
- **右侧内容区**：当前页面渲染
- **右侧面板**：支持拖拽调整宽度（SplitPane）

## 主题

自动跟随系统亮色/暗色模式，使用 CSS 变量实现一致主题。

## 相关文档

- [项目管理](/projects) — 项目 Canvas 详解
- [终端管理](/terminal) — 终端会话
- [认证与授权](/auth) — 登录与鉴权
- [系统设置](/settings) — 设置面板
