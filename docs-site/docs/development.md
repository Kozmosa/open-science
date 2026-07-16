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

前端开发使用 worktree 隔离的 API、deterministic fixture worker、Vite 和 synthetic committed-v2 state，
不要复用 production、shared staging 或 L2 资源：

```bash
npm --prefix frontend ci

# 启动 Vite HMR + FastAPI reload + deterministic fixture worker
bash scripts/dev.sh up --profile full

# 查看派生 URL、PID、日志和健康状态
bash scripts/dev.sh status --profile full

# 经 Vite proxy 验证 health、capabilities 和领域 projection
bash scripts/dev.sh smoke --profile full

# 查看日志并停止
bash scripts/dev.sh logs --profile full all --follow
bash scripts/dev.sh down --profile full

# 删除并重新生成由工具 marker 管理的 synthetic state
bash scripts/dev.sh reset --profile full
```

可选择以下 deterministic profile：

| Profile | 用途 |
| --- | --- |
| `full` | F1–F10 代表性正常状态，默认值 |
| `empty` | 新用户和空状态 |
| `permissions` | owner、viewer、editor、publish 与 archived 权限 |
| `failures` | failed、partial、stale、launch_unknown 与 stopped 状态 |
| `large` | 40 Projects、120 Workspaces、500 Tasks、250 Papers 的滚动与列表压力 |

实例 ID、端口和 `/tmp/openscience-dev/<instance-id>/` 路径按 worktree、branch 和 profile
稳定派生。不同 worktree 不再争用 5173/8000；端口被未知进程占用时命令会失败并提示
override，不会主动杀进程。凭据只存在 repo 外的权限受限文件和 Vite proxy process 中，
不会注入浏览器 bundle。

需要用真实登录页面检查 owner/editor/viewer/admin 权限时，先获取凭据文件路径：

```bash
bash scripts/dev.sh prepare --profile full --json
```

输出中的 `login_credentials_path` 指向 repo 外的 `0600` JSON。密码不会写入 marker、日志、
Git 或浏览器 bundle；同一 managed fixture 会稳定复用，执行 `reset` 后重新生成。

## 反馈链与辅助场景

### 快速开发

```bash
bash scripts/dev.sh up --profile full --mode dev
```

前端使用 Vite HMR，后端使用 uvicorn reload。fixture 本身不会留下可 claim 的 Task 或
Literature 工作项；页面主动创建的新 Task、文献检查/摘要和 Today 刷新由 marker-guarded
fixture worker 通过正式持久化与 projection 路径确定性完成。worker 不启动真实 Harness，
也不调用 arXiv、LLM、environment detect、Docker、staging 或 production。

### 本地 production preview

```bash
bash scripts/dev.sh up --profile full --mode preview
bash scripts/dev.sh smoke --profile full --mode preview
```

preview 启动前强制执行 production frontend build，API 不启用 reload。它验证本地装配，
但仍不是 Docker/L2 或 release evidence。

### 故障场景

```bash
# 切换 profile/fault 时先 reset managed synthetic instance
bash scripts/dev.sh reset --profile full --fault-profile transient
bash scripts/dev.sh up --profile full --fault-profile transient
```

| Fault profile | 行为 |
| --- | --- |
| `none` | 默认正常路径 |
| `latency` | API 响应增加固定延迟，并返回可在 Network 中识别的 fault header |
| `transient` | 每个 GET/HEAD 路径首次返回 503，后续恢复 |
| `resources` | Resources 两个数据源返回 503，用于 partial/global failure 检查 |
| `offline` | 除 health/auth/docs 外的 API 返回 503 |

fault profile 只对 marker-owned synthetic state 生效；production 自动禁用，personal state
直接拒绝。`status`、`logs`、`down` 应继续使用与启动时相同的 profile/fault 参数，避免把
“请求参数不一致”误判成服务退化。

### MSW 离线辅助

`VITE_USE_MOCK=true` 只用于后端刻意不可用时的纯前端工作或 Vitest。它在浏览器入口按需
加载 contract-validated MSW scenario，所有业务函数仍调用统一 `/api` HTTP client；未处理
的 `/api/**` 会硬失败，字体、JS、CSS 等非 API 资产继续绕过。

```bash
VITE_USE_MOCK=true npm --prefix frontend run dev -- \
  --host 127.0.0.1 --port <explicit-unused-port> --strictPort
```

MSW 可以验证组件、URL、表单和确定性状态迁移，但不能证明 FastAPI、SQLite projection、
JWT、fixture worker 或 Vite proxy 正常。真实 synthetic API 才是 DevTools 主验证面。

### 证据边界

| Lane | 能证明 | 不能替代 |
| --- | --- | --- |
| Vitest + MSW | 前端合同、组件交互、离线状态机 | 真实 API、JWT、worker、浏览器渲染 |
| `dev.sh --mode dev` | HMR、reload、真实 synthetic API/JWT/worker、DevTools 流程 | production bundle、L1、L2–L4 |
| `dev.sh --mode preview` | production bundle + isolated API 的本地装配 | Docker、shared staging、release acceptance |
| `ci.sh l0/l1` | 确定性代码门禁 | 手工 DOM/computed style/Network/focus 验收 |

### Browser / DevTools preflight

```bash
# 基础工具与依赖
bash scripts/dev.sh doctor --profile full

# 发现 Chrome/MCP 配置并实际启动一次隔离 CDP
bash scripts/dev.sh doctor --profile full --browser
```

系统 snap Chromium 会被拒绝。preflight 不修改用户配置、不自动升级 MCP，也不会自动加
`--no-sandbox`。Chrome/CDP 成功证明 headless 主机具备真实浏览器能力；是否在当前 agent
会话暴露 browser tool 仍取决于启动时加载的 MCP 配置，配置变化后必须重启 session。

DevTools 手工检查、HTTP smoke、L0/L1、L2 和 release acceptance 是不同证据层，不能互相
替代。F1–F10 的 DOM、computed style、Network、focus 和响应式验收继续记录在客户端延期
验收清单中，不新增 Playwright merge gate。

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
