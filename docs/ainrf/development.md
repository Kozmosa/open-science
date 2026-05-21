---
aliases:
  - 开发指南
  - Development Guide
  - development
tags:
  - ainrf
  - development
  - testing
  - linting
  - performance
  - docs
  - obsidian-note
source_repo: scholar-agent
source_path: docs/ainrf/development.md
last_local_commit: workspace aggregate
---

# 开发指南

> [!abstract]
> AINRF 开发指南涵盖后端与前端测试、代码质量检查、性能审计和文档构建等日常开发任务。

## 后端测试

使用 `pytest` 运行后端测试套件：

```bash
# 运行全量测试
uv run pytest

# 运行单项测试（带详细输出）
uv run pytest tests/test_file.py -v

# 运行特定测试类或函数
uv run pytest tests/test_file.py::TestClass::test_method -v
```

测试覆盖 CLI、API 路由、数据库操作、环境管理、终端会话和任务执行等核心模块。测试配置文件位于 `pyproject.toml`。

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

规则集和行长度（100）在 `pyproject.toml` 中配置。提交前 pre-commit hook 会自动运行 ruff。

## 前端类型检查

前端使用 TypeScript 项目引用（project references），必须以 `tsc -b` 方式运行：

```bash
cd frontend && node_modules/.bin/tsc -b
```

注意：不支持 `npx tsc -p tsconfig.app.json --noEmit` 或从仓库根目录运行 `tsc`。

## 前端测试

使用 Vitest 运行前端测试：

```bash
cd frontend && npm run test:run
```

测试覆盖组件渲染、用户交互、API 调用和路由行为。

## 前端构建

生产构建：

```bash
cd frontend && npm run build
```

构建产物输出至 `frontend/dist/`。

## 性能审计

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

每个目标输出结构化报告，用于识别性能瓶颈和优化方向。

## 文档构建与预览

文档站基于 MkDocs（Material 主题），从 `docs/` 源文件构建：

```bash
# 完整构建（含 wikilink 验证）
scripts/build.sh

# 本地预览服务器
scripts/serve.sh

# 或直接通过 uv 运行
uv run python scripts/build_html_notes.py build
uv run python scripts/build_html_notes.py serve
```

构建脚本会验证所有 wikilinks 可解析，并在发现未解析引用时使构建失败。

## Git 分支管理

建议使用 git worktree 隔离特性开发工作区，避免频繁切换分支：

```bash
# 创建特性分支的工作区
git worktree add .claude/worktrees/my-feature-branch my-feature-branch

# 工作完成后清理
git worktree remove .claude/worktrees/my-feature-branch
git branch -d my-feature-branch
```

始终基于 `master` 分支创建新分支，提交前运行 lint 和测试。

## 关联笔记

- [[index]]
