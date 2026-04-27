<p align="center">
  <h1 align="center">AINRF</h1>
</p>

<p align="center">
  <strong>AI-Native Research Framework 的研究控制面</strong><br />
  让 Agent 任务、远程环境、持久终端与工作区浏览器进入同一个可观察、可编排、可复现的运行时界面。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-runtime-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img alt="React" src="https://img.shields.io/badge/React-WebUI-61DAFB?style=for-the-badge&logo=react&logoColor=black" />
  <img alt="Vite" src="https://img.shields.io/badge/Vite-frontend-646CFF?style=for-the-badge&logo=vite&logoColor=white" />
  <img alt="uv" src="https://img.shields.io/badge/uv-managed-DE5FE9?style=for-the-badge" />
</p>

<p align="center">
  <a href="#-why-ainrf">Why</a> ·
  <a href="#-core-capabilities">Capabilities</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="#-development">Development</a>
</p>

---

## ✨ What is AINRF?

**AINRF** 将 AI-native research workflow 从“脚本 + 远程机器 + 临时终端 + 手工记录”收敛成一个工程化控制面：

- 用 `ainrf` CLI 启动和管理本地 runtime；
- 用 FastAPI 暴露环境、任务、终端和工作区 API；
- 用 React WebUI 观察任务状态、输出流、远程环境和持久终端；
- 用版本化 docs / ref-repos 保存研究设计、参考项目和历史决策输入。

它不是一个普通笔记仓库，也不是单一 Web 控制台。AINRF 的目标是成为研究开发者操作 Agent runtime 的 **control surface**：任务可追踪、环境可探测、终端可接管、工作区可打开、artifact 可回放。

---

## 🖥️ Console Preview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ AINRF Console                                           Task | Running: 1    │
├──────────────┬───────────────────────────────────────────────────────────────┤
│  Terminal    │  Task Workspace                                               │
│  Tasks       │  ┌─ Task runs ──────────────────────────────────────────────┐  │
│  Workspaces  │  │ train-eval-gpu        running      seq: 184              │  │
│  Containers  │  │ paper-review-agent    queued       env: cpu-lab          │  │
│  Settings    │  └─────────────────────────────────────────────────────────┘  │
│              │                                                               │
│ Environment  │  Output Timeline                                              │
│ gpu-lab      │  #182 stdout  loading dataset shards...                       │
│ SSH ready    │  #183 stdout  evaluating checkpoint...                        │
│ CUDA profile │  #184 system  artifact snapshot persisted                     │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

---

## 🚀 Why AINRF?

研究型 Agent 项目通常会同时面对几类复杂度：

| 问题 | AINRF 的处理方式 |
| --- | --- |
| 任务散落在终端、脚本和远程机器里 | Task Harness 统一任务创建、状态、输出 replay / stream 与 runtime artifact |
| 本地/远程环境不透明 | Environment Control Plane 管理 SSH 目标、探测结果、默认环境与运行时画像 |
| Agent 执行过程不可观察 | WebUI 提供任务列表、inspect 面板、输出时间线与错误摘要 |
| 需要临时接管或观察终端 | Terminal Bench 提供持久 tmux 会话与浏览器终端连接 |
| 代码工作区和运行时割裂 | Workspace Browser 通过托管 code-server 暴露项目工作区 |

---

## 🧩 Core Capabilities

### Task Harness

- 创建面向 workspace / environment binding 的 Agent task。
- 持久化 prompt layers、binding snapshot、launch payload 与结果摘要。
- 支持任务状态轮询、输出 replay、SSE stream、gap refill 与错误摘要。
- WebUI 中提供 Kimi-style task sidebar、任务 inspect 面板和输出时间线。

### Environment Control Plane

- 管理 SSH-backed compute environments。
- 支持环境探测：SSH、workdir、Python、uv、conda、CUDA、GPU、Claude CLI 等运行时信号。
- 支持项目默认环境、环境引用和 per-project runtime override。
- 为 terminal、task harness、workspace browser 提供统一环境选择来源。

### Terminal / Workspace

- 持久个人终端：通过 tmux session 保持长生命周期交互面。
- 浏览器终端：本地环境直接连接，远程环境通过 SSH bridge 交互。
- 任务观察与接管：支持 observe-only / takeover 等终端访问语义。
- 工作区浏览器：按所选环境启动和管理 code-server workspace surface。

### CLI / API / WebUI

- `ainrf` CLI 作为本地 runtime 入口。
- FastAPI backend 提供 `/v1` API surface。
- React + Vite + Tailwind WebUI 提供统一控制台。
- `scripts/webui.sh` 串联前后端本地开发体验。

---

## 🏗️ Architecture

```text
┌──────────────────────┐
│      React WebUI      │
│  Tasks / Terminal /   │
│  Containers / Settings│
└───────────┬──────────┘
            │ HTTP / WebSocket / SSE
┌───────────▼──────────┐
│     FastAPI Backend   │
│  routes + services    │
└───────────┬──────────┘
            │
┌───────────▼──────────────────────────────────────────────┐
│                    AINRF Runtime                          │
│  environments │ tasks │ terminal │ workspace │ artifacts  │
└───────────┬───────────────────────────────┬──────────────┘
            │                               │
┌───────────▼──────────┐        ┌───────────▼──────────┐
│ Local project state   │        │ Remote environments   │
│ .ainrf / docs / logs  │        │ SSH / tmux / runtime  │
└──────────────────────┘        └──────────────────────┘
```

---

## ⚡ Quick Start

> AINRF 使用 `uv` 管理 Python 运行环境。建议在命令前显式设置 `UV_CACHE_DIR`，避免污染项目目录或共享环境。

```bash
# 查看 CLI 入口
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf --help

# 启动后端 API
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf serve

# 启动 WebUI 本地联调入口
scripts/webui.sh
```

前端单独开发：

```bash
cd frontend
npm run test:run
npm run build
```

文档站点构建：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/build_html_notes.py build
```

---

## 📁 Project Layout

```text
.
├── src/ainrf/        # Python package: CLI, API, runtime services
├── frontend/         # React + Vite WebUI
├── tests/            # Python test suite
├── scripts/          # 本地开发、WebUI、docs 构建辅助脚本
├── docs/             # AINRF 产品文档、设计笔记和知识资产
├── ref-repos/        # 只读参考仓库，用于产品设计与对照研究
└── PROJECT_BASIS.md  # 长期工程约束与协作规则
```

---

## 🛠️ Tech Stack

| Layer | Stack |
| --- | --- |
| CLI / Runtime | Python 3.13, Typer, structlog, Pydantic |
| Backend API | FastAPI, Uvicorn, WebSocket, SSE |
| Remote Control | asyncssh, tmux-oriented terminal sessions |
| Frontend | React 19, Vite 8, TypeScript, Tailwind CSS, TanStack Query |
| Docs | MkDocs, Material for MkDocs, Mermaid |
| Quality | pytest, ruff, ty, Vitest, Testing Library |

---

## ✅ Development

Python checks:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests
UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests
UV_CACHE_DIR=/tmp/uv-cache uv run ty check
```

Frontend checks:

```bash
cd frontend
npm run test:run
npm run build
```

Docs checks:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/build_html_notes.py build
```

---

## 📚 Documentation

- [AINRF 使用文档](docs/ainrf/index.md)
- [项目长期工程约束](PROJECT_BASIS.md)
- [框架设计与 RFC](docs/framework/)
- [参考项目调研](docs/projects/)
- [跨项目总结](docs/summary/)

---

## 🧭 Status

AINRF 已具备可安装 CLI、FastAPI backend、React WebUI，以及围绕 environment / terminal / task / workspace browser 的核心运行时表面。项目处于持续维护和产品化收敛阶段，适合用于本地 AI-native research workflow 的运行控制、观察和工程验证。

---

## 🤝 Contributing

这个仓库优先保持工程约束、运行时契约和文档入口的一致性。贡献前建议先阅读：

- `PROJECT_BASIS.md`
- `CLAUDE.md`
- `docs/ainrf/index.md`

提交信息使用 Conventional Commits，例如：

```text
feat: add environment detection panel
fix: harden task stream replay
refactor: split runtime artifact helpers
```

---

## 📄 License

License 信息以后续仓库配置为准。
