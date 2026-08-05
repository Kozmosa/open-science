# OpenScience Backend and Runtime

`src/ainrf/` 是 OpenScience 的 canonical Python package、backend API 与
runtime 实现目录。本文只提供子系统导航；长期项目规则以
[`../../PROJECT_BASIS.md`](../../PROJECT_BASIS.md) 为最高 authority，当前
产品架构、HTTP contract、generated transport 与 compatibility inventory
见 [`../../docs-site/docs/architecture.md`](../../docs-site/docs/architecture.md)。

## 身份与兼容边界

- OpenScience 是用户可见产品品牌，`openscience` 是产品 CLI。
- `ainrf` 是 canonical Python import、backend runtime、状态路径、Linux
  identity、deployment、telemetry 与 backend configuration namespace。
- Backend 配置使用 `AINRF_*`；对应 `OPENSCIENCE_*` backend 变量是长期
  compatibility aliases。仓库开发、CI 与编排变量可按项目规则使用
  `OPENSCIENCE_*`。
- `ainrf` CLI 与 `openscience` CLI 都受支持；不要把 canonical backend
  identity 当作待删除的 legacy debt。

## 当前模块边界

- `api/`: FastAPI routes、HTTP application construction、server lifecycle
  与完整 CLI 的 HTTP Adapter composition。
- `command.py`: 不依赖 HTTP Adapter 的通用 CLI command composition。
- `domain/`、`domain_control/`: Project、Workspace、Environment、Context、
  Conversation 等 current application Modules 与 control-plane facade。
- `harness_engine/`: Claude Code、Agent SDK、Codex 等执行引擎 Adapter。
- `agentic_researcher/`: researcher presets、engine configuration 与显式
  compatibility 数据类型；不拥有 Task CRUD 或 lifecycle writes。
- `db/`: current fresh-install baselines、migration registry 与 persistence
  support。
- `auth/`、`security/`: 身份、session、API-key 与安全边界。
- `terminal/`、`workspaces/`、`files/`: terminal、workspace 与 tenant-aware
  文件能力。
- `literature/`: Literature application Module、durable checks 与 Adapter。
- `development/`: deterministic local fixture、profile 与开发状态生成。

Current Task 行为由 Conversation Domain 的 Task、Turn、Item、
TurnSubmission、RuntimeExecution 与 EngineConversationBinding 拥有。普通
产品路径不得重新引入旧 Attempt/RuntimeSession authority、legacy read
fallback、长期 dual-read 或 dual-write。

## 依赖与 Interface 规则

- Product import graph 必须无 cycle。
- Non-API Module 不得通过直接、惰性、动态或字符串 import 反向依赖
  `ainrf.api`。
- Canonical product HTTP prefix 是 `/api`；`/v1/models` 与 `/v1/messages`
  是独立、长期支持的 external-model protocol Interface。
- FastAPI/Pydantic OpenAPI 是 transport schema authority。修改 schema 或
  route 后运行 `npm --prefix frontend run generate:transport`，并用
  `npm --prefix frontend run check:transport` 验证 drift。

## 常用命令

从仓库根目录运行：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run openscience --help
bash scripts/test.sh unit
bash scripts/test.sh api
bash scripts/ci.sh l0
bash scripts/ci.sh l1
```

Python 代码必须兼容 `>=3.13` 并具有严格类型标注。完整提交门禁为
`bash scripts/ci.sh l1`。

## 权限与运行时安全

Tenant workspace 和 home 由 `ainrf_<tenant>` Linux 用户拥有；backend
用户 `ainrf` 不能假定可写。涉及 tenant provisioning、上传、workspace
创建或 subprocess execution 时，必须阅读
[`../../.rules/multi-tenant-permissions.md`](../../.rules/multi-tenant-permissions.md)。

涉及 frontend deployment、DevTools、tenant permission、SSH/tmux fallback
或 session-scoped config 排障时，还必须先阅读
[`../../dev-bitter-lesson.md`](../../dev-bitter-lesson.md)。
