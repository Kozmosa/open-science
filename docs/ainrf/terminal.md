---
aliases:
  - AINRF 终端管理
  - AINRF Terminal
  - terminal
tags:
  - ainrf
  - terminal
  - docs
  - obsidian-note
source_repo: scholar-agent
source_path: docs/ainrf/terminal.md
---

# 终端管理

> [!abstract]
> AINRF 终端子系统管理 Personal Session（个人终端）和 Agent Session（任务代理终端），支持 Localhost 直连与远程 SSH+tmux 两种模式。

## Session 类型

| 类型            | 用途                     | 生命周期管理              |
| --------------- | ------------------------ | ------------------------- |
| Personal Session | 用户手动连接的终端       | `ensure_personal_session` |
| Agent Session   | 任务代理自动使用的终端   | `ensure_agent_session`    |

每个环境绑定（`UserEnvironmentBinding`）对应一个 session pair，包含 personal 和 agent 两条会话记录。

## 连接模式

### Localhost 环境

当环境的 host 为 `127.0.0.1` 或 `localhost`，且无 proxy_jump/proxy_command 时：

- 跳过 tmux，直接启动 `/bin/bash -l` PTY
- TIOCSWINSZ resize 直接作用于 shell 进程
- 持久化由 attachment 生命周期管理

### 远程环境

通过 SSH 连接到远程主机并创建 tmux 会话：

- SSH 连接使用 `~/.ssh/config`、自定义端口、IdentityFile、ProxyJump/ProxyCommand
- tmux session name 使用 blake2s 哈希生成：`p-{hash}`（personal）或 `a-{hash}`（agent）
- 远程 tmux 可用性通过 `command -v tmux` 预检

## WebSocket 附件机制

```
/terminal/attachments/{attachment_id}/ws?token={token}
```

流程：

1. **创建附件**：`POST /terminal/session` 返回 attachment_id 和过期时间
2. **WebSocket 连接**：前端使用 attachment_id + token 建立 WebSocket 连接
3. **PTY 转发**：WebSocket 全双工通道，服务端通过 `os.read`/`os.write` 操作 PTY master fd
4. **backpressure 控制**：高水位标记暂停 reader，低水位标记恢复

### 消息协议

前端发送 JSON 消息：

```json
// 输入
{"type": "input", "data": "ls -la\n"}

// 调整尺寸
{"type": "resize", "cols": 120, "rows": 40}
```

服务端发送：

```json
// 输出
{"type": "output", "data": "[1m..."}

// 退出状态
{"type": "status", "status": "exited", "return_code": 0}
```

### 附件模式

- `INTERACTIVE`：允许键盘输入
- `OBSERVE`：只读观察，输入消息会被拒绝（关闭连接）

## Session 生命周期

```
create → attach → detach → reset
```

### Create

调用 `SessionManager.ensure_personal_session`：

1. 绑定用户与环境（`user_environment_bindings` 表）
2. 创建 session pair（`user_session_pairs` 表）
3. 通过 TmuxAdapter 确保 tmux 会话存在
4. 生成 attachment 目标

### Attach

1. `TerminalAttachmentBroker.create_attachment` 创建附件记录
2. 记录 attach 时间戳
3. 返回 attachment_id 供 WebSocket 连接

### Detach

1. `TerminalAttachmentBroker.detach_attachment` 解除附件
2. 可选的 `SessionManager.reconcile` 刷新本地状态

### Reset

1. `TerminalAttachmentBroker.detach_attachment` 断开当前附件
2. `TmuxAdapter.kill_session` 杀掉 tmux 会话
3. `TmuxAdapter.ensure_personal_session` 重新创建 tmux 会话
4. 生成新附件

## 终端 Resize

WebSocket 收到 `resize` 消息后：

1. `resize_terminal` 调用 `TIOCSWINSZ` ioctl 调整 PTY 尺寸
2. 调用 `SessionManager.resize_tmux_window` 调整 tmux 窗口尺寸（best-effort）
3. resize 失败不阻断前端操作

## SessionManager 本地状态

状态存储在 SQLite 数据库中，路径为 `{state_root}/runtime/terminal_state.sqlite3`。

### 核心表

**user_environment_bindings**

| 列               | 说明                         |
| ---------------- | ---------------------------- |
| binding_id       | 主键                         |
| user_id          | 用户 ID                      |
| environment_id   | 环境 ID                      |
| remote_login_user | 远程登录用户名               |
| default_shell    | 默认 shell（如 /bin/bash）   |
| default_workdir  | 默认工作目录                 |
| mux_kind         | 终端复用器类型（当前固定 tmux） |

**user_session_pairs**

| 列                  | 说明                          |
| ------------------- | ----------------------------- |
| binding_id          | 主键，关联 bindings           |
| personal_session_name | Personal tmux session 名称  |
| agent_session_name  | Agent tmux session 名称       |
| personal_status     | IDLE / RUNNING / FAILED       |
| agent_status        | IDLE / RUNNING / FAILED       |
| last_verified_at    | 上次 tmux 状态验证时间        |
| last_personal_attach_at | 上次个人终端连接时间      |
| last_agent_attach_at    | 上次代理终端连接时间      |

状态验证：每次读取 pair 时调用 `_refresh_pair` 检查 tmux 会话是否存在，自动更新状态。

## API 端点

| 方法   | 路径                            | 说明                              |
| ------ | ------------------------------- | --------------------------------- |
| GET    | `/terminal/session`             | 读取当前 session 记录             |
| GET    | `/terminal/session-pairs`       | 列出用户的所有 session pairs      |
| POST   | `/terminal/session`             | 创建/获取 personal session        |
| DELETE | `/terminal/session`             | 断开附件                          |
| POST   | `/terminal/session/reset`       | 重置 personal session             |
| POST   | `/terminal/session/exec`        | 在环境中执行命令（非交互式）      |
| WS     | `/terminal/attachments/{id}/ws` | WebSocket 终端连接                |

## 关联文档

- [[projects]]：任务代理终端在项目中自动管理
