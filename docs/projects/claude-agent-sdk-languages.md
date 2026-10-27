---
aliases:
  - Claude Agent SDK 语言支持调研
  - Claude Agent SDK 官方语言对照
  - Claude Agent SDK Go 绑定调研
tags:
  - openscience
  - reference-project
  - agent-sdk
  - claude-code
  - harness-engine
  - go-binding
source_repo: anthropics/claude-agent-sdk-typescript + anthropics/claude-agent-sdk-python
source_url: https://code.claude.com/docs/en/agent-sdk/overview
researched_at: 2026-10-26
---

# Claude Agent SDK 官方语言支持对照

> [!abstract]
> Claude Agent SDK 官方仅支持**两种语言:TypeScript 与 Python**。两者不是两套协议,而是同一 `claude` CLI stream-json stdio 协议之上的两份语言封装——spawn 参数、JSONL 消息类型、control_request/response 双向通道完全同构,功能面主要由 CLI 版本决定;差异在封装进度(TS 包 0.3.x 领先 Python 包 0.2.x)与少量各自先行的控制方法。**开放度与量级不对称:Python SDK 完整开源(src 约 1.08 万行代码、测试约两倍于源码),TS SDK 实现闭源**(仓库仅 issue 跟踪 + 示例约 1.1k 行,发布产物是 0.86 MB minified 单文件 bundle)。社区 Go 绑定存在且活跃维护(头部 severity1/claude-agent-sdk-go 176★、2026-10 仍在发版),但均非官方。其他语言官方指引是直接以子进程运行 CLI(`claude -p --output-format json`)——OpenScience 的 `claude_code.py` 正是这条路线的等价实现,`agent_sdk.py` 则是 Python 官方 SDK 路线,两条官方路线我们都已在用。本笔记与同日的 claudecodeui stdio 交互调研(TS SDK 0.3.165 拆包实证)同源互补。

## 1. 结论与证据边界

- **官方语言数:2(TypeScript、Python)**。官方文档 Agent SDK overview(code.claude.com,由 docs.claude.com/platform.claude.com 重定向而来)只列出 TypeScript 与 Python 两份参考,没有第三种官方语言;对其他语言,文档给出的官方建议是"把 CLI 当子进程运行"(`-p` + `--output-format json`)。
- anthropics GitHub 组织验证:Agent SDK 相关仓库只有 `claude-agent-sdk-typescript` 与 `claude-agent-sdk-python` 两个实现仓库,外加 `claude-agent-sdk-demos`(示例)与 `agent-sdk-workshop`(教程)两个辅助仓库。
- **易混淆项**:`anthropic-sdk-go` / `-java` / `-php` / `-csharp` / `-ruby` 是 Anthropic **Messages API 客户端 SDK**(直连模型 API),不是 Agent SDK;引用资料时不要混为一谈。
- 调研快照:2026-10-26。方式:官方文档 + npm/PyPI registry API + anthropics 组织仓库清单 + 两包源码抽查(npm 0.3.165 拆包、Python main 分支 `subprocess_cli.py` / `client.py`)。文中版本号为当日快照。

## 2. 两个官方 SDK 的版本与形态对照

| 维度 | TypeScript | Python |
| --- | --- | --- |
| 包 | `@anthropic-ai/claude-agent-sdk`(npm) | `claude-agent-sdk`(PyPI) |
| 仓库 | anthropics/claude-agent-sdk-typescript | anthropics/claude-agent-sdk-python |
| 快照最新版 | 0.3.310(2026-10-23 发布) | 0.2.174(2026-10-24 发布,累计 146 个版本) |
| 首个版本 | 2025-09-27(0.0.4,更名重启) | 2025-09-28(0.0.23) |
| 前身 | `claude-code-sdk`(npm,2025-05-20 仅发过 0.1.0) | 无 |
| 宿主运行时 | Node.js(`node cli.js …`)或原生二进制 | Python ≥ 3.10,asyncio |
| 子进程机制 | `child_process.spawn` | `asyncio.create_subprocess_exec` |
| 传输层 | 同一 CLI + 同一 JSONL stdio 协议(见下) | 同左 |

**协议同构的证据**(本轮对两包源码的抽查):

- 两侧 spawn 参数一致:`claude --output-format stream-json --verbose --input-format stream-json`,按选项追加 `--permission-prompt-tool stdio`(注册 canUseTool 回调时)、`--include-partial-messages`、`--resume`、`--session-id`、`--model`、`--mcp-config` 等。
- 双向 control 协议一致:stdin 上的 `initialize` / `interrupt` / `set_model` / `stop_task` 等请求,stdout 上的 `can_use_tool` / `hook_callback` / `mcp_message` 等 CLI 回调,`control_response` / `control_cancel_request` / `keep_alive` 帧。
- stderr 处理策略一致:默认不接管(TS 侧为 `"ignore"`,仅 `DEBUG_CLAUDE_AGENT_SDK` 或注册回调时接管;Python 侧仅注册回调时 PIPE)——所以两侧都必须显式传 stderr 回调才能拿到 CLI 报错(我们 `agent_sdk.py` 已这样做;claudecodeui 没有做,其错误信息因此依赖 generator throw + 安装检查)。
- stdin 生命周期语义一致:字符串 prompt 被判为单轮流,首个 `result` 即关 stdin;异步消息流则耗尽后再关。这解释了 claudecodeui 的 held-prompt-stream 模式(保持输入流挂起以保活后台任务)在 Python 侧同样需要。

## 3. 能力面对照(control 方法,按快照源码)

| 能力 | TS 0.3.x | Python 0.2.x |
| --- | --- | --- |
| interrupt / set_permission_mode / set_model / rewind_files / stop_task | ✓ | ✓ |
| canUseTool 审批回调、hooks、部分流式(include partial messages)、SDK 内置 MCP | ✓ | ✓ |
| background_tasks、set_max_thinking_tokens、apply/get_settings | ✓ | — |
| generate_session_title、side_question、enable_remote_control、cancel_async_message、seed_read_state | ✓ | — |
| get_context_usage、reconnect/toggle_mcp_server、get_mcp_status、get_server_info | — | ✓ |

- 交集覆盖了我们关心的全部生命周期操作(interrupt、stop_task、rewind_files);两侧各有先行方法,总体 TS 迭代更快(主版本线 0.3.x vs 0.2.x 错位)。
- 功能差异本质是**封装进度差,不是协议差**:协议由 CLI 侧定义,任何一侧缺失的方法都可在 CLI 升级后补齐封装。

## 4. 第三方使用方实证(claudecodeui)与 OpenScience 现状

- claudecodeui(2026-10-26 main 快照)主聊天通道 = TS SDK `^0.3.165`,在 SDK 之上实现了 held-stdin、审批桥(canUseTool → WebSocket → 浏览器)、后台任务跟踪(`task_started`/`task_notification` 折叠 + `stopTask`)、`--resume-session-at` 中途恢复等模式(细节见同日会话内的 claudecodeui stdio 调研结论)。
- OpenScience `src/ainrf/harness_engine/engines/agent_sdk.py` = Python SDK 路线:`pyproject.toml` 锁 `claude_agent_sdk>=0.1.77`,当前安装 0.2.99(快照最新 0.2.174);已使用 `can_use_tool`、`include_partial_messages=True`、stderr 回调、`resume`,与 claudecodeui 的 TS 用法逐项同构。
- OpenScience `src/ainrf/harness_engine/engines/claude_code.py` = 官方"其他语言"指引的等价实现:直接子进程 `claude -p`(一次性、无 stream-json、无审批回调)。两条官方路线在我们仓库里互为备份。

## 5. 代码量级与源码开放度(tokei,2026-10-26 快照)

| 对象 | 统计口径 | 文件数 | 总行数 | 代码行 | 备注 |
| --- | --- | --- | --- | --- | --- |
| Python SDK 仓库 `src/` | 实现 | 26 | 13,529 | 10,797 | 完整开源实现 |
| Python SDK tests+examples+e2e | 测试/示例 | 80 | 33,794 | 26,662 | 测试代码量约为源码 2 倍 |
| TS SDK 仓库(全仓,除 .git) | — | 29 | 3,915 | 1,426 | 其中 TS 仅 16 文件 1,380 行(基本是 session-store 示例),余为 Markdown/Shell |
| TS npm 产物 `sdk.mjs` | 发布产物 | 1 | 119 | 111 | **876,564 字节(≈0.86 MB)minified bundle**,行数无参考意义 |
| Go 绑定 severity1 `src` | 实现(除测试) | 54 | 16,071 | 10,984 | 含测试时 104 文件 50,109 行 |
| Go 绑定 character-ai `src` | 实现(除测试) | 48 | 10,314 | 7,720 | 含测试时 81 文件 18,089 行 |

关键发现:**TS 与 Python 的源码开放度完全不对称**。`claude-agent-sdk-python` 是常规开源仓库;`claude-agent-sdk-typescript` 仓库里没有实现源码(这也解释了 GitHub 把它的主语言标成 Shell),它实际充当 issue 跟踪 + CHANGELOG + 示例仓库,实现只以构建产物形式随 npm 包分发(CLI 本体再由平台二进制包如 `@anthropic-ai/claude-agent-sdk-linux-x64/claude` 单独分发——与 Python SDK spawn 的是同一个 CLI)。所以"0.86 MB minified"只能说明 TS 封装层的量级不小,无法对等比较源码规模;真正可审计、可参照移植的官方实现只有 Python 一份(约 1.1 万行,与两个 Go 绑定的非测试源码量级相同)。

## 6. 社区 Go 绑定现况(2026-10-26 快照)

官方无 Go SDK,但社区绑定存在且活跃。对"claude agent sdk / claude-code sdk + language:Go"的 GitHub 搜索取头部候选逐项核实(stars、push、release、协议实现):

| 仓库 | ★ | 创建 | 最近 push | 状态 | 说明 |
| --- | --- | --- | --- | --- | --- |
| severity1/claude-agent-sdk-go | 176 | 2025-08 | 2026-10-05 | 活跃 | 由 claude-code-sdk-go 更名而来;v0.10.0(2026-10-05);源码 54 文件 1.6 万行+大量测试(含 mock CLI);包装同一 stream-json stdio 协议 |
| lancekrogers/claude-code-go | 53 | 2025-05 | 2026-10-20 | 活跃 | 非官方 Claude Code Go agent SDK |
| character-ai/claude-agent-sdk-go | 32 | 2026-01 | 2026-09-08 | 活跃 | Character AI 组织背景;v0.1.0(2026-09-08);源码 48 文件约 1.03 万行;包装同一协议 |
| schlunsen/claude-agent-sdk-go | 25 | 2025-10 | 2026-10-09 | 活跃 | 自述为官方 Python SDK 的 Go 移植 |
| yukifoo/claude-code-sdk-go | 12 | 2025-05 | 2025-06-18 | 停滞 | 一年多无更新,不算活跃 |

- 上述活跃项目均为 MIT、均以外部 `claude` CLI 子进程 + stream-json stdio 为传输(severity1 与 character-ai 的源码已 grep 验证含 `--input-format stream-json` 传输实现),协议上与两个官方 SDK 同构;差异只在封装进度与质量。
- 相关但非绑定:`agent-dance/agent-adaptor`(74★,统一封装 codex/claude/cursor 本地执行的 Go SDK);axonhub、bifrost、OpenAgentCore 等是网关/编排产品,不属于 SDK 绑定。
- 无任何社区绑定获得 Anthropic 官方背书;官方对 Go 的态度仍是"子进程跑 CLI"(§1)。

## 7. 对 OpenScience 的含义

1. **语言数不构成选型压力**:两种官方路线我们都已落地(Python SDK 引擎 + 裸 CLI 引擎),且 stdio 协议同构意味着两条路的行为模型可以互相印证——claudecodeui 的 TS 经验可直接翻译到 `agent_sdk.py`。
2. **升级窗口**:本地 0.2.99 落后最新 0.2.174。若做"任务详情页流式 + 后台任务停止"(见 [[openhands-agent-platform]] §7.A 与 claudecodeui 调研),Python 0.2.x 已具备 `stop_task` 与 task 事件,无需换语言;`background_tasks` 等 TS 独有方法当前无需求。
3. **若未来宿主不是 Python/Node**:官方答案就是裸 CLI 子进程(我们已有该模式的成熟实现),不存在等待官方 SDK 的阻塞;若想省掉 stdio 协议封装,社区 Go 绑定(§6,severity1/character-ai 均活跃且 MIT)可直接复用或对照移植,但需接受无官方背书、跟随 CLI 协议演进的维护成本。ACP([[openhands-agent-platform]] §7.B.4)是另一条多语言编排路线,与 SDK 路线互补而非替代。

## 8. 主要来源

- 官方 Agent SDK 文档:https://code.claude.com/docs/en/agent-sdk/overview (docs.claude.com / platform.claude.com 依次重定向)
- npm registry API:`@anthropic-ai/claude-agent-sdk`(0.3.310,2026-10-23)、`claude-code-sdk`(2025-05-20,单版本)
- PyPI registry API:`claude-agent-sdk`(0.2.174,2026-10-24;首发 0.0.23,2025-09-28)
- anthropics 组织仓库清单:https://github.com/anthropics (claude-agent-sdk-typescript / claude-agent-sdk-python / -demos / agent-sdk-workshop)
- 源码抽查:npm 包 0.3.165 `sdk.mjs`(ProcessTransport.spawn 参数、control 协议);Python main 分支 `src/claude_agent_sdk/_internal/transport/subprocess_cli.py` 与 `client.py`(spawn 参数、ClaudeSDKClient 控制方法)
- 代码量级:`tokei`(cargo 安装版)对 anthropics/claude-agent-sdk-typescript、anthropics/claude-agent-sdk-python(main 浅克隆)、npm 包 `sdk.mjs`、severity1 与 character-ai 两个 Go 绑定(main 浅克隆,含/不含 `*_test.go` 两种口径)的统计
- Go 绑定:GitHub repository search("claude agent sdk / claude-code sdk, language:Go")+ 各仓库 API 元数据(stars/pushed_at/releases)+ 源码协议验证
- 本地对照:`pyproject.toml`、`src/ainrf/harness_engine/engines/agent_sdk.py`、`src/ainrf/harness_engine/engines/claude_code.py`、siteboon/claudecodeui main 快照
