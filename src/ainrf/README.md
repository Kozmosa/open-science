# AINRF Runtime README

本文档描述 `src/ainrf` 当前保留运行时的职责、启动方式、环境变量和联调路径。

## 0. 内网 WebUI 一键启动

如果你的目标是直接在内网机器上联调或使用当前 WebUI，优先使用仓库根目录脚本：

```bash
scripts/webui.sh
scripts/webui.sh dev
scripts/webui.sh preview
scripts/webui.sh dev --backend-public
scripts/webui.sh preview --backend-public
```

默认模式是 `dev`。脚本会自动：

- 使用 `UV_CACHE_DIR=/tmp/uv-cache`（若当前环境未显式设置）
- 在仓库根目录准备 `./.ainrf/`
- 在 `./.ainrf/webui.env` 里生成或复用本地 WebUI service key
- 把对应 hash 合并进 `./.ainrf/config.json` 的 `api_key_hashes`
- 启动后端 `uv run ainrf serve --host 127.0.0.1 --port 8000 --state-root .ainrf`
- 启动前端 dev server（`0.0.0.0:5173`）或 preview server（`0.0.0.0:4173`）

默认暴露策略是：

- 前端监听 `0.0.0.0`
- 后端默认只监听 `127.0.0.1`

此时浏览器统一通过前端代理访问 `/api`、`/code` 与 `/terminal`，不再需要手动设置
`VITE_AINRF_API_KEY`，浏览器端也不会持有 service key。只有在明确需要让内网直接访问后端 API 时，再额外加 `--backend-public`。

`./.ainrf/webui.env` 属于本地运行态文件；开启 `--backend-public` 时，脚本只会提示这个文件路径，不会把 key 明文回显到终端。

## 1. 目录定位

> [!success]
> Cleanup gate passed：旧的 task/orchestrator/WebUI product center 已从当前 runtime 主路径移除；现阶段只保留 daemon/API health、container profile 和 SSH health probing 这组最小存活表面，作为后续 realignment 的起点。

`src/ainrf` 当前仅保留以下稳定能力：

- CLI 入口（`ainrf` 命令）
- FastAPI 服务（仅健康检查与 API key 中间件）
- 容器连接配置持久化（`ainrf container add`）
- environments 控制面（环境 CRUD、手动探测、最近结果展示）
- SSH 容器健康探测与远端命令执行
- API daemon 启停支持

主要入口文件：

- `src/ainrf/cli.py`: CLI 命令定义
- `src/ainrf/server.py`: API 服务启动与 daemon 启动
- `src/ainrf/api/app.py`: FastAPI 应用装配
- `src/ainrf/api/routes/health.py`: 健康检查路由
- `src/ainrf/execution/ssh.py`: SSH 执行与健康探测

## 2. 当前支持的 CLI 表面

### 2.1 启动 API 服务

如果只是要启动当前 WebUI，优先回到上一节使用 `scripts/webui.sh`。本节的 `ainrf serve` 仍然保留，作为更底层的后端 API 入口。

前台模式：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf serve --host 127.0.0.1 --port 8000
```

daemon 模式：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf serve --daemon --host 127.0.0.1 --port 8000
```

首次无配置示例（会触发交互式 API key 初始化）：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf serve --host 127.0.0.1 --port 8000
```

### 2.2 交互式添加 Container

可以通过 CLI 交互方式，从 SSH 命令直接生成可复用的容器配置：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf container add --state-root .ainrf
```

交互输入示例：

- profile 名称: `gpu-main`
- SSH 命令: `ssh -p 2222 researcher@gpu-server-01 -i ~/.ssh/id_ed25519`
- 远端项目目录: `/workspace/projects/attention-study`
- SSH 密码: `<可留空，留空表示 key-based auth>`

命令会把配置保存到 `.ainrf/config.json` 的 `container_profiles`，并默认设置为 `default_container_profile`。

## 3. 运行前准备

### 3.1 Python 与依赖

项目通过 `uv` 管理依赖，推荐直接使用：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf --help
```

### 3.2 首次运行 Onboarding

AINRF 默认使用当前工作目录下的 `./.ainrf/` 作为 state root；如果通过 `--state-root`
显式指定，则改用指定目录。

当目录内还不存在 `./.ainrf/config.json`，且也没有通过环境变量提供
`AINRF_API_KEY_HASHES` 时，第一次执行底层 `ainrf serve` 会自动进入交互式 onboarding。
如果希望显式执行同一流程，也可以直接运行：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf onboard
```

onboarding 至少会创建 `./.ainrf/config.json`。最小可用配置只需要包含
`api_key_hashes`；在同一交互流程里，用户也可以选择顺手写入一个默认的 container
profile，供后续容器连接配置复用。

### 3.3 API Key 配置（启动 API 必需）

低层 API 中间件读取 `AINRF_API_KEY_HASHES`（SHA-256 哈希值，支持逗号分隔多个 key）。
如果你走 `scripts/webui.sh`，则不需要手动设置这个环境变量；脚本会自动把本地 WebUI service key 的 hash 写入 `./.ainrf/config.json`，并由前端代理层代为注入 `X-API-Key`。

生成哈希示例：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -c "from ainrf.api.config import hash_api_key; print(hash_api_key('your-api-key'))"
```

设置环境变量：

```bash
export AINRF_API_KEY_HASHES=<hash1>,<hash2>
```

首次启动时，如果既没有设置 `AINRF_API_KEY_HASHES`，也没有 `.ainrf/config.json` 中的
`api_key_hashes`，`ainrf serve` 会自动进入交互式引导，要求输入 API key 并把其哈希
写入 `.ainrf/config.json`。

### 3.3 容器连接配置

`ContainerConfig.from_env()` 读取：

- `AINRF_CONTAINER_HOST`（必需）
- `AINRF_CONTAINER_PORT`（默认 `22`）
- `AINRF_CONTAINER_USER`（默认 `root`）
- `AINRF_CONTAINER_SSH_KEY_PATH`
- `AINRF_CONTAINER_PASSWORD`（可选，密码认证）
- `AINRF_CONTAINER_CONNECT_TIMEOUT`（默认 `30`）
- `AINRF_CONTAINER_COMMAND_TIMEOUT`（默认 `3600`）
- `AINRF_CONTAINER_PROJECT_DIR`（默认 `/workspace/projects`）

如果未设置环境变量，也可以从 `.ainrf/config.json` 的默认容器 profile 读取。

## 4. API 路由说明

### 4.1 Terminal Bench keepalive personal session 与 Workspace Browser

Terminal Bench MVP 现已切换为 `xterm.js + PTY/WebSocket`，不再依赖 `ttyd` 二进制。
联调时只需要确保后端 API 服务可启动，并且前端能访问同源 WebSocket 地址即可。

Terminal 与 Workspace 现均绑定到选中的 `environment`。当前项目在这一轮固定为隐式项目键 `default`，并可通过 project environment refs API 声明默认环境与 runtime-only overrides。
Terminal Slice 1 已经从“单全局 PTY”切换为“daemon 单用户 × environment 的 tmux-backed personal session + attachment attach/detach/reset”模型：

- 每个 `user × environment` 对应一个长期保活的 personal tmux session。
- 浏览器 websocket 只代表短生命周期 attachment，不再等同于底层 session 本体。
- 页面刷新、浏览器关闭或显式 `Detach` 都不会销毁底层 tmux session。
- 服务重启后会从 `state_root/runtime/terminal_state.sqlite3` 读取 binding / session pair 元数据，并按 tmux 状态做 reconcile。
- V1 多路复用后端固定为 `tmux`；如果 daemon 主机或远端 environment 缺少 `tmux`，terminal ensure/reset 会直接失败，不再回退到旧 PTY shell。

Workspace Browser 在本地环境下依赖本机可执行的 `code-server` 二进制；联调前请先确认：

```bash
code-server --version
```

当前 runtime API 只暴露以下最小表面：

- 公共健康检查路径：
  - `GET /health`
  - `GET /v1/health`
- environment 控制面路径（均受 API key 中间件保护）：
  - `GET /environments`
  - `POST /environments`
  - `GET /environments/{id}`
  - `PATCH /environments/{id}`
  - `DELETE /environments/{id}`
  - `POST /environments/{id}/detect`
  - `GET /v1/environments`
  - `POST /v1/environments`
  - `GET /v1/environments/{id}`
  - `PATCH /v1/environments/{id}`
  - `DELETE /v1/environments/{id}`
  - `POST /v1/environments/{id}/detect`
- project environment refs 路径（均受 API key 中间件保护）：
  - `GET /projects/{project_id}/environment-refs`
  - `POST /projects/{project_id}/environment-refs`
  - `PATCH /projects/{project_id}/environment-refs/{environment_id}`
  - `DELETE /projects/{project_id}/environment-refs/{environment_id}`
  - `GET /v1/projects/{project_id}/environment-refs`
  - `POST /v1/projects/{project_id}/environment-refs`
  - `PATCH /v1/projects/{project_id}/environment-refs/{environment_id}`
  - `DELETE /v1/projects/{project_id}/environment-refs/{environment_id}`
- Terminal Bench MVP 路径（均受 API key 中间件保护）：
  - `GET /terminal/session?environment_id=...`
  - `POST /terminal/session`
  - `DELETE /terminal/session`
  - `POST /terminal/session/reset`
  - `GET /v1/terminal/session?environment_id=...`
  - `POST /v1/terminal/session`
  - `DELETE /v1/terminal/session`
  - `POST /v1/terminal/session/reset`
- code-server 状态路径（均受 API key 中间件保护）：
  - `GET /code/status?environment_id=...`
  - `GET /v1/code/status?environment_id=...`
- code-server session 控制路径（均受 API key 中间件保护）：
  - `POST /code/session`
  - `DELETE /code/session`
  - `POST /v1/code/session`
  - `DELETE /v1/code/session`
- managed code-server browser 路径（均受 API key 中间件保护）：
  - `GET /code/`
  - `GET /v1/code/`
  - `GET /code/...` 与 `GET /v1/code/...` 下的嵌套静态资源 / 子路径，均由 API 反向代理到受管 `code-server`

其中 terminal session API 现在控制按 environment 绑定的 keepalive personal tmux session：

- `GET /terminal/session?environment_id=...`：读取当前用户在所选 environment 下的 personal session 摘要；若还未 ensure，则返回 `idle`
- `POST /terminal/session`：按 `environment_id` 执行 idempotent ensure，并返回当前浏览器的短期 attachment 信息（`attachment_id`、`attachment_expires_at`、`terminal_ws_url`）
- `DELETE /terminal/session?environment_id=...&attachment_id=...`：只 detach 当前 attachment，不销毁底层 personal tmux session
- `POST /terminal/session/reset`：显式 kill 并重建 personal tmux session，然后返回新的 attachment
- `GET /terminal/attachments/{attachment_id}/ws?token=...`：terminal attachment 数据通道

`/v1/terminal/session` 与 `/v1/terminal/session/reset` 提供相同语义的版本化镜像路径。

`auth_kind=password` 的 environment 只支持 terminal 内交互式输入密码；不会通过 API 注入 secret。

code-server 相关路径只暴露当前 daemon 受管的单实例 workspace browser：

- `GET /code/status?environment_id=...`：读取当前所选 environment 对应的 workspace 状态
- `POST /code/session`：按 `environment_id` 执行 idempotent ensure
- `DELETE /code/session`：关闭当前受管 workspace session
- `GET /code/`：通过 API 代理访问 browser 入口
- `/v1/code/status` 与 `/v1/code/` 提供相同语义的版本化镜像路径

`auth_kind=password` 的 environment 对 `/code/session` 固定返回 `409`，因为受管 workspace 不支持非交互 password-auth。

如果本机未安装 `code-server`，或受管 session 尚未 ensure，API 仍会正常启动；此时 `/code/status` 会返回 `unavailable`，`/code/` 会返回不可用错误，而不会阻断主服务启动。

已移除的旧 task 路径不会再由应用注册；在提供有效 API key 后会返回 `404`。

## 5. 状态目录结构

默认状态根目录为 `.ainrf/`（可通过 `--state-root` 指定）。

当前实际使用的典型结构：

```text
.ainrf/
  config.json
  runtime/
    ainrf-api.pid
    ainrf-api.log
    terminal_state.sqlite3
```

`terminal_state.sqlite3` 当前持久化两张 terminal keepalive 主表：

- `user_environment_bindings`
- `user_session_pairs`

## 6. 调试与排障

### 6.1 常见问题

- API 启动报 `AINRF API key hashes are not configured`
- 原因：未设置 `AINRF_API_KEY_HASHES` 且 `.ainrf/config.json` 无哈希

- 容器健康检查显示 `degraded`
- 原因：SSH 不可达、Claude CLI 不可用、Anthropic key 缺失，或远端项目目录不可写

- daemon 启动失败
- 原因：端口不可用，或健康检查在超时窗口内未就绪

### 6.2 推荐验证

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_api_auth.py tests/test_api_health.py tests/test_api_v1_routes.py tests/test_cli.py tests/test_server.py tests/test_execution_ssh.py -q
python -m compileall src/ainrf
```

## 7. 对外说明

`src/ainrf` 目录当前主要服务于最小化运行时验证，不再包含任务编排、工件存储、事件流、解析流程或 WebUI 能力。
如果你继续收缩或调整运行时行为，请同步更新：

- 对应测试（`tests/`）
- 工作日志（`docs/LLM-Working/worklog/YYYY-MM-DD.md`）
