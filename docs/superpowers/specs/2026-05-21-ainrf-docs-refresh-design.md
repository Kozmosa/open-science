# AINRF Documentation Refresh Design

## 目标

将 `docs/ainrf/` 从单页过时文档更新为与当前代码基线匹配的完整导航页集。

## 文档结构

```
docs/ainrf/
├── index.md           # 总览 + 导航枢纽
├── quickstart.md      # 快速开始
├── cli.md             # CLI 命令参考
├── webui.md           # WebUI 页面总览
├── auth.md            # 认证与鉴权
├── projects.md        # 项目管理与 Canvas
├── terminal.md        # 终端与会话管理
├── workspace.md       # Workspace 与文件浏览器
├── sessions.md        # Session 与 Attempt 链
├── timeline.md        # Timeline / Gantt 图表
├── resources.md       # 资源监控
├── settings.md        # 设置与管理员面板
├── development.md     # 开发与验证命令
└── presentations/     # 演讲材料（已有）
```

## 各页内容要点

### index.md — 总览
- AINRF 是什么（一条线）
- 核心子系统列表（每项 1-2 行描述 + 链接）
- 快速导航表

### quickstart.md — 快速开始
- 前置依赖（uv, Node.js）
- `uv run ainrf onboard`
- `scripts/webui.sh`
- 默认账户（admin/admin）

### cli.md — CLI 参考
- `onboard` — 初始化
- `serve` — 启动后端
- `stop` — 停止服务
- `login` — 登录获取 token
- `container` — 容器管理
- 常用 flags（`--host`, `--port`, `--state-root`）

### webui.md — WebUI 总览
- 布局（侧边栏 + 内容区）
- 各页面路由表
- 亮色/暗色模式

### auth.md — 认证
- JWT Bearer Token 机制
- 登录/注册页面
- 用户角色（admin/member）
- Admin 面板功能（用户管理、环境授权、项目协作者）
- 密码修改流程

### projects.md — 项目与 Canvas
- 项目侧边栏
- Canvas 节点与边（ReactFlow DAG）
- 手动连线（拖拽连接）
- 自动连线（按 created_at 排序）
- 布局持久化（localStorage）
- 任务创建表单

### terminal.md — 终端
- Personal / Agent 会话模式
- 本地 localhost bash 直连（跳过 tmux）
- 远程环境 SSH
- WebSocket 附件

### workspace.md — 工作区
- Workspace 管理（CRUD）
- 文件浏览器（目录树、文件查看）
- Monaco 编辑器预览
- 默认 workspaces

### sessions.md — 会话追踪
- Session 与 Attempt 的关系
- 任务关联的 session 链
- 耗时与成本统计

### timeline.md — 时间线
- Gantt 图展示任务执行时间线
- 任务状态颜色编码

### resources.md — 资源监控
- GPU 监控
- CPU / 内存
- 进程树
- 环境检测

### settings.md — 设置面板
- General 页
- Admin: 用户管理 tab
- Admin: 环境授权 tab
- Admin: 项目协作者 tab
- Skill 仓库管理

### development.md — 开发命令
- 后端测试 / lint / 格式化
- 前端类型检查 / 测试 / 构建
- 性能审计工具（`scripts/perf/`）

## 编写原则
- 每页保持 50-150 行，简洁为主
- 命令示例使用真实可运行的命令
- 前端页面用路由路径标注
- 关联到 `docs/superpowers/specs/` 下的设计规范

## 验证
1. `scripts/build.sh` — mkdocs 构建通过
2. 所有 wikilink 可解析
3. 所有 CLI 命令在当前代码中可运行
