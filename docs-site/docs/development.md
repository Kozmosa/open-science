---
title: 开发指南
description: 后端与前端测试、代码质量检查、性能审计与文档构建等日常开发任务。
---

OpenScience 开发指南涵盖后端与前端测试、代码质量检查、性能审计和文档构建等日常开发任务。

## 统一 CI 入口

日常开发优先使用仓库内统一入口：

```bash
# L0：快速 agent / 开发反馈
bash scripts/ci.sh l0

# L1：后端、前端与文档的完整确定性门禁，不启动 Docker 或外部服务
bash scripts/ci.sh l1

# 查看 L0-L4 五层边界
bash scripts/ci.sh describe
```

L0/L1 使用固定上限的 worker：pytest 默认 8，Vitest 默认 4。共享服务器上不要使用 `-n auto`；如需进一步降低资源占用，可设置 `OPENSCIENCE_PYTEST_WORKERS=4 OPENSCIENCE_VITEST_WORKERS=2`。

## 后端测试

使用 `pytest` 运行后端测试套件：

```bash
# 运行完整后端测试（并行安全测试 + 串行 race 测试）
bash scripts/test.sh all

# 运行单项测试（带详细输出）
uv run pytest tests/test_file.py -v

# 运行特定测试类或函数
uv run pytest tests/test_file.py::TestClass::test_method -v
```

测试覆盖 CLI、API 路由、数据库操作、环境管理、终端会话和任务执行等核心模块。测试标记（markers）：`api`、`unit`、`middleware`、`engine`、`cli`、`integration`、`slow`。

## 后端 Lint / 格式化

使用 Ruff 进行代码检查和自动格式化：

```bash
# 检查 lint 问题
uv run ruff check .

# 检查格式问题
uv run ruff format --check .

# 自动修复 lint 并格式化
uv run ruff check --fix .
uv run ruff format .
```

规则集和行长度（100）在 `pyproject.toml` 中配置。运行 `pre-commit install` 后会按仓库配置安装 pre-commit 与 pre-push 两类 hook：pre-commit 阶段运行 Ruff，pre-push 阶段运行 L0。Git hook 是本地便利工具，L1 GitHub-hosted gate 才是共享门禁。

## 前端类型检查

前端使用 TypeScript 项目引用（project references），必须以 `tsc -b` 方式运行：

```bash
cd frontend && node_modules/.bin/tsc -b
```

:::note
不支持 `npx tsc -p tsconfig.app.json --noEmit` 或从仓库根目录运行 `tsc`。
:::

## 前端测试

使用 Vitest 运行前端测试：

```bash
cd frontend && npm run test:run
```

测试覆盖组件渲染、用户交互、API 调用和路由行为。

## 前端构建

```bash
cd frontend && npm run build
```

构建产物输出至 `frontend/dist/`。

## 隔离的 v2 前端开发环境

领域前端 F5–F10 需要真实的 v2 capability、Project/Workspace 读模型和 domain worker
heartbeat。使用仓库内的合成 fixture，不要为日常前端开发复用 production、shared staging
或 L2 资源：

```bash
npm --prefix frontend ci

# 只准备或核对 synthetic committed-v2 state
bash scripts/frontend-dev.sh prepare

# 同时启动 API、空闲 domain worker 和 Vite HMR
bash scripts/frontend-dev.sh run
```

默认状态目录为 `/tmp/openscience-frontend-dev`，API 为 `127.0.0.1:8000`，Vite 为
`127.0.0.1:5173`。可通过 `OPENSCIENCE_FRONTEND_DEV_STATE_ROOT`、
`OPENSCIENCE_FRONTEND_DEV_API_PORT` 和 `OPENSCIENCE_FRONTEND_DEV_PORT` 覆盖。
fixture 只写合成 Project、Workspace、Environment 和权限状态，并拒绝把状态目录放入任意
Git worktree。

该入口不是 L2 或浏览器 E2E 门禁。headless 开发阶段运行 Vitest、API contract、lint 和
build；真实 DOM、焦点、computed style、loaded asset 与窄屏验收在具备 DevTools 的客户端
环境单独完成。

## 实验性性能审计

:::caution
现有性能脚本已从 GitHub CI 退役，目前不提供阻塞性性能结论。它们保留为 L3 deep verification 的实验输入，待认证、状态断言、运行 harness 和版本化阈值重建后再恢复自动化。
:::

需要 API benchmark 依赖时显式安装 perf group：`uv sync --group perf`。

性能审计脚本按目标分层组织在 `scripts/perf/` 目录下：

```bash
# 数据库索引审计
uv run python scripts/perf/run-all.py --target db

# API 基准测试
uv run python scripts/perf/run-all.py --target backend

# Bundle 分析
uv run python scripts/perf/run-all.py --target frontend

# 全栈审计（数据库 + backend + frontend）
uv run python scripts/perf/run-all.py --target all
```

## 文档构建与预览

文档站基于 VitePress 构建：

```bash
cd docs-site

# 开发模式（热更新）
npm run dev

# 生产构建
npm run build

# 本地预览构建结果
npm run preview
```

## Git 分支管理

建议使用 git worktree 隔离特性开发工作区：

```bash
# 创建特性分支的工作区
git worktree add .claude/worktrees/my-feature-branch my-feature-branch

# 工作完成后清理
git worktree remove .claude/worktrees/my-feature-branch
git branch -d my-feature-branch
```

始终基于 `master` 分支创建新分支，提交前运行 lint 和测试。

## 相关文档

- [部署概览](/deployment/) — 生产部署方式
- [开发指南](/development) — 开发工作流
