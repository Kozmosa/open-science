---
aliases: [WebUI, 前端页面, webui]
tags: [ainrf, webui, frontend]
---

# WebUI 总览

## 启动

```bash
scripts/webui.sh dev     # 开发模式 (Vite HMR, 端口 5173)
scripts/webui.sh         # 预览模式 (构建后, 端口 4173)
```

## 架构

- 前端：React 19 + TypeScript + Vite 8
- UI 组件库：Tailwind CSS v4 + 自定义组件
- 状态管理：TanStack React Query v5
- Canvas：@xyflow/react v12 (ReactFlow)
- 终端：xterm.js
- 编辑器：Monaco Editor (懒加载)

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
| `/timeline` | TimelinePage | 时间线 (Gantt 图) |
| `/resources` | ResourcesPage | 资源监控 (GPU/CPU/内存) |
| `/environments` | EnvironmentsPage | 环境管理 |
| `/workspaces` | WorkspacesPage | 工作区管理 |
| `/settings` | SettingsPage | 设置面板 |

## 布局

- 左侧可折叠侧边栏：导航菜单 + 用户信息 + 登出
- 右侧内容区：当前页面渲染
- 右侧面板支持拖拽调整宽度（SplitPane）

## 主题

自动跟随系统亮色/暗色模式，使用 CSS 变量实现一致主题。

## 关联笔记

- [[projects]] — 项目 Canvas 详解
- [[terminal]] — 终端会话
- [[auth]] — 登录与鉴权
- [[settings]] — 设置面板
