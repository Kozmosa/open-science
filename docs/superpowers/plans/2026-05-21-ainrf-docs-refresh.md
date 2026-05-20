# AINRF Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `docs/ainrf/index.md` and create 12 new documentation pages covering all AINRF subsystems to match the current codebase baseline (May 2026).

**Architecture:** Each .md file is a self-contained page with Obsidian frontmatter, wikilinks, and callouts. Pages form a navigation hierarchy: `index.md` → subsystem pages → detailed specs in `docs/superpowers/specs/`.

**Tech Stack:** Markdown, Obsidian wikilink syntax, MkDocs Material theme

---

## File Map

| File | Lines (est.) | Content |
|------|-------------|---------|
| `docs/ainrf/index.md` | ~60 | Complete rewrite: overview + nav table |
| `docs/ainrf/quickstart.md` | ~80 | Installation, onboard, first launch |
| `docs/ainrf/cli.md` | ~80 | All CLI commands with examples |
| `docs/ainrf/webui.md` | ~80 | Page routing, layout, theming |
| `docs/ainrf/auth.md` | ~100 | JWT, roles, admin panel |
| `docs/ainrf/projects.md` | ~80 | Canvas, edges, task creation |
| `docs/ainrf/terminal.md` | ~80 | Sessions, localhost/remote, WebSocket |
| `docs/ainrf/workspace.md` | ~60 | Workspace CRUD, file browser |
| `docs/ainrf/sessions.md` | ~60 | Session/attempt model, cost tracking |
| `docs/ainrf/timeline.md` | ~40 | Gantt chart, time visualization |
| `docs/ainrf/resources.md` | ~60 | GPU/CPU/memory monitoring |
| `docs/ainrf/settings.md` | ~60 | Settings tabs, admin functions |
| `docs/ainrf/development.md` | ~80 | Dev commands, perf tools, testing |

---

### Task 1: Core Pages (index, quickstart, cli, webui)

**Files:**
- Rewrite: `docs/ainrf/index.md`
- Create: `docs/ainrf/quickstart.md`
- Create: `docs/ainrf/cli.md`
- Create: `docs/ainrf/webui.md`

- [ ] **Step 1: Write `docs/ainrf/index.md`**

```markdown
---
aliases: [AINRF 使用文档, AINRF Usage Guide]
tags: [ainrf, docs, index]
source_repo: scholar-agent
---

# AINRF 使用文档

> [!abstract]
> AINRF 是 scholar-agent 的核心前后端产品，提供 CLI、REST API、WebUI、Terminal、
> Workspace Browser、任务引擎、多用户鉴权等完整能力。本目录是用户文档入口。

## 核心子系统

| 子系统 | 说明 | 文档 |
|--------|------|------|
| 快速开始 | 安装、初始化、启动 | [[quickstart]] |
| CLI | 命令行工具参考 | [[cli]] |
| WebUI | 前端页面与布局 | [[webui]] |
| 认证 | JWT 鉴权、用户角色、Admin 面板 | [[auth]] |
| 项目管理 | Canvas DAG 可视化、任务创建 | [[projects]] |
| 终端 | Personal/Agent 会话、本地/远程 | [[terminal]] |
| 工作区 | Workspace 管理、文件浏览器 | [[workspace]] |
| 会话追踪 | Session/Attempt 链、成本统计 | [[sessions]] |
| 时间线 | Gantt 图、任务时间分布 | [[timeline]] |
| 资源监控 | GPU/CPU/内存、进程树 | [[resources]] |
| 设置面板 | 通用设置、Admin 管理 | [[settings]] |
| 开发命令 | 测试、构建、性能审计 | [[development]] |

## 关联笔记

- [[index]]
- 设计规范：`docs/superpowers/specs/`
- 实施计划：`docs/superpowers/plans/`
- 历史文档：`docs/archive/`
```

- [ ] **Step 2: Write `docs/ainrf/quickstart.md`**

```markdown
---
aliases: [Quick Start, 快速开始]
tags: [ainrf, quickstart]
---

# 快速开始

## 前置依赖

- Python 3.13+
- Node.js 22+
- uv (`pip install uv`)

## 初始化

```bash
uv run ainrf onboard
```

## 启动

```bash
scripts/webui.sh        # 前后端联合启动
scripts/webui.sh dev    # 开发模式 (Vite HMR)
```

## 默认账户

首次启动时自动创建 admin 账户：
- 用户名：`admin`
- 密码：`admin`
- 首次登录后提示修改密码

## 访问

- WebUI: `http://localhost:5173`
- API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

## 后续步骤

- [[cli]] — 命令行工具详解
- [[webui]] — WebUI 页面导航
```

- [ ] **Step 3: Write `docs/ainrf/cli.md`**

```markdown
---
aliases: [CLI Reference, 命令行参考]
tags: [ainrf, cli]
---

# CLI 命令参考

所有命令通过 `uv run ainrf` 执行。

## onboard

初始化本地状态与配置，首次使用前必须执行。

```bash
uv run ainrf onboard
```

## serve

启动后端 API 服务。

```bash
uv run ainrf serve
uv run ainrf serve --host 0.0.0.0 --port 8000 --state-root ~/.ainrf
```

参数：
- `--host`：监听地址（默认 127.0.0.1）
- `--port`：监听端口（默认 8000）
- `--state-root`：状态存储目录（默认 ~/.ainrf）

## stop

停止由 `serve` 启动的后台 daemon。

```bash
uv run ainrf stop
```

## login

登录并缓存 JWT token 到本地。

```bash
uv run ainrf login
uv run ainrf login --username admin --password admin
```

## container

管理可复用的容器/环境配置。

```bash
uv run ainrf container add
uv run ainrf container list
```

## 关联笔记

- [[quickstart]] — 首次使用流程
- [[webui]] — WebUI 访问方式
```

- [ ] **Step 4: Write `docs/ainrf/webui.md`**

```markdown
---
aliases: [WebUI, 前端页面]
tags: [ainrf, webui, frontend]
---

# WebUI 总览

## 访问

- 开发模式：`http://localhost:5173`（Vite HMR）
- 预览模式：`http://localhost:4173`（构建后预览）
- 通过 `scripts/webui.sh dev` 启动开发模式

## 布局

- 左侧边栏：导航菜单 + 用户信息
- 右侧内容区：各页面内容

## 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | LoginPage | 登录 |
| `/register` | RegisterPage | 注册（需审批） |
| `/change-password` | ChangePasswordPage | 修改密码 |
| `/projects` | ProjectsPage | 项目 Canvas + 任务管理 |
| `/tasks` | TasksPage | 任务列表与详情 |
| `/terminal` | TerminalPage | 终端会话 |
| `/files` | FileBrowserPage | 文件浏览器 |
| `/sessions` | SessionsPage | 会话追踪 |
| `/timeline` | TimelinePage | 时间线 (Gantt) |
| `/resources` | ResourcesPage | 资源监控 |
| `/environments` | EnvironmentsPage | 环境管理 |
| `/workspaces` | WorkspacesPage | 工作区管理 |
| `/settings` | SettingsPage | 设置面板 |

## 主题

支持亮色/暗色模式自动切换（跟随系统设置）。

## 关联笔记

- [[projects]] — 项目 Canvas
- [[terminal]] — 终端页面
- [[auth]] — 登录与认证
```

- [ ] **Step 5: Commit**

```bash
git add docs/ainrf/index.md docs/ainrf/quickstart.md docs/ainrf/cli.md docs/ainrf/webui.md
git commit -m "docs(ainrf): add core pages — index, quickstart, CLI, WebUI overview"
```

---

### Task 2: Feature Pages (auth, projects, terminal)

**Files:**
- Create: `docs/ainrf/auth.md`
- Create: `docs/ainrf/projects.md`
- Create: `docs/ainrf/terminal.md`

- [ ] **Step 1: Write `docs/ainrf/auth.md`**

Content covering:
- JWT Bearer Token 认证机制
- 登录 (`/auth/login`)、注册 (`/auth/register`)、刷新 (`/auth/refresh`)
- 用户角色：`admin`（全权限）、`member`（资源所有者或协作者）
- 用户状态：`pending` → `active` / `disabled`
- Admin 面板：用户审批、密码重置、环境授权、项目协作者管理
- `ainrf login` CLI 命令
- 关联：`docs/superpowers/specs/2026-05-18-ainrf-auth-phase-b-design.md`

- [ ] **Step 2: Write `docs/ainrf/projects.md`**

Content covering:
- 项目侧边栏：项目列表、选择、搜索
- ReactFlow Canvas：节点（TaskNode）、边（TaskEdge）
- 手动连线：从 source handle 拖拽到 target handle
- 自动连线：按 `created_at` 时间排序自动连接
- 布局：dagre 自动布局 + localStorage 持久化
- 任务创建：TaskCreateForm（环境/工作区/技能/引擎选择）
- 关联：`docs/superpowers/specs/2026-05-20-frontend-loading-optimization-design.md`

- [ ] **Step 3: Write `docs/ainrf/terminal.md`**

Content covering:
- Personal Session（个人终端）vs Agent Session（任务代理终端）
- Localhost 环境：直接 bash 启动（跳过 tmux）
- 远程环境：SSH + tmux
- WebSocket 附件 (`/terminal/attach`)
- Session 生命周期：create → attach → detach → reset
- 关联：`docs/superpowers/specs/2026-05-20-n1-sync-io-fix-design.md`

- [ ] **Step 4: Commit**

```bash
git add docs/ainrf/auth.md docs/ainrf/projects.md docs/ainrf/terminal.md
git commit -m "docs(ainrf): add feature pages — auth, projects, terminal"
```

---

### Task 3: Feature Pages (workspace, sessions, timeline)

**Files:**
- Create: `docs/ainrf/workspace.md`
- Create: `docs/ainrf/sessions.md`
- Create: `docs/ainrf/timeline.md`

- [ ] **Step 1: Write `docs/ainrf/workspace.md`**

Content covering:
- Workspace CRUD：创建、列表、编辑、删除
- 默认 workspace（`workspace-default`）
- 文件浏览器：目录树导航、文件列表、Monaco 编辑器预览
- 默认工作目录（`~/.ainrf_workspaces/default`）
- 关联：`docs/superpowers/specs/2026-05-13-workspaces-page-baseline-design.md`

- [ ] **Step 2: Write `docs/ainrf/sessions.md`**

Content covering:
- Session：一次用户交互会话的容器
- Attempt：Session 内的单次执行尝试
- Session 状态：active → completed / archived
- 成本追踪：`total_cost_usd`、`duration_ms`
- Session 页面：列表、筛选、详情
- 关联：`docs/superpowers/specs/2026-05-17-ainrf-session-chain-design.md`

- [ ] **Step 3: Write `docs/ainrf/timeline.md`**

Content covering:
- Gantt 图：任务按时间轴的横向条形图
- 颜色编码：running（蓝色）、succeeded（绿色）、failed（红色）
- 时间范围缩放
- 关联：`docs/superpowers/specs/2026-05-18-ainrf-timeline/`

- [ ] **Step 4: Commit**

```bash
git add docs/ainrf/workspace.md docs/ainrf/sessions.md docs/ainrf/timeline.md
git commit -m "docs(ainrf): add feature pages — workspace, sessions, timeline"
```

---

### Task 4: Feature Pages (resources, settings, development)

**Files:**
- Create: `docs/ainrf/resources.md`
- Create: `docs/ainrf/settings.md`
- Create: `docs/ainrf/development.md`

- [ ] **Step 1: Write `docs/ainrf/resources.md`**

Content covering:
- GPU 监控：nvidia-smi 数据（型号、显存、利用率）
- CPU 监控：进程 CPU 百分比
- 内存监控：`/proc/meminfo` 数据
- 进程树：AINRF 相关进程的父子关系
- 2 秒轮询间隔
- 环境检测：SSH 可达性、Claude 可用性

- [ ] **Step 2: Write `docs/ainrf/settings.md`**

Content covering:
- General tab：默认 workspace、默认环境、默认 task profile
- Users tab（Admin only）：用户列表、审批、禁用、密码重置
- Env Access tab（Admin only）：环境授权、用户配额
- Collaborators tab：项目协作者（member/viewer 角色）
- Skill Repositories：ARIS 技能安装/管理

- [ ] **Step 3: Write `docs/ainrf/development.md`**

Content covering:
- 后端测试：`uv run pytest`
- 后端 lint：`uv run ruff check .`
- 前端类型检查：`cd frontend && node_modules/.bin/tsc -b`
- 前端测试：`cd frontend && npm run test:run`
- 前端构建：`cd frontend && npm run build`
- 性能审计：`uv run python scripts/perf/run-all.py --target db`
- 文档构建：`scripts/build.sh`
- 关联：`docs/superpowers/plans/`

- [ ] **Step 4: Commit**

```bash
git add docs/ainrf/resources.md docs/ainrf/settings.md docs/ainrf/development.md
git commit -m "docs(ainrf): add feature pages — resources, settings, development"
```

---

### Task 5: Integration Verification

- [ ] **Step 1: Verify all wikilinks resolve**

```bash
uv run python scripts/build_html_notes.py build
```

Expected: build passes, no unresolved wikilink errors.

- [ ] **Step 2: Check all files exist**

```bash
ls -la docs/ainrf/*.md
```

Expected: 13 .md files.

- [ ] **Step 3: Commit worklog**

```bash
git add docs/LLM-Working/worklog/2026-05-21.md
git commit -m "chore: update worklog with AINRF docs refresh"
```

---

## Verification Checklist

1. `uv run python scripts/build_html_notes.py build` — mkdocs build passes
2. All 13 `docs/ainrf/*.md` files present
3. All wikilinks resolve without errors
4. All CLI commands documented are actually runnable
5. All page routes documented match actual `App.tsx` routes
