---
aliases:
  - OpenHands 调研
  - OpenHands Agent 平台对照分析
tags:
  - openscience
  - reference-project
  - agent-platform
  - agent-orchestration
  - harness-engine
source_repo: OpenHands
source_url: https://github.com/OpenHands/OpenHands
researched_at: 2026-10-26
---

# OpenHands 2026 现状与 OpenScience 对照分析

> [!abstract]
> OpenHands(原 OpenDevin,All-Hands-AI)在 2025–2026 完成了彻底重组:主仓库变成纯 TypeScript 的 "Agent Canvas"(可经 ACP 编排 Claude Code、Codex 等 coding agent 的自托管控制台),自研 agent 能力整体迁入 MIT 协议的 V1 Software Agent SDK(`OpenHands/software-agent-sdk`)。对 OpenScience 而言,它最值得借鉴的不是"换用它的 agent",而是四个已经打磨成熟的子系统设计:面向前端的事件流 WebSocket(含断线重放)、dispatcher 侧的会话所有权租约 fencing、Agent Skills 规范的渐进披露技能机制,以及 pause/interrupt/消息排队的精确语义。反过来,多租户隔离、领域模型与发布纪律是 OpenScience 领先的部分;开源版没有 checkpoint/restore,自研 agent loop 与 K8s warm pool 也不符合我们的架构取向,不建议引入。

## 1. 调研范围与证据边界

- 调研方式:纯 web 调研(本仓库 `ref-repos/` 未克隆 OpenHands),一手来源为 GitHub 仓库与 raw 源码、`docs.openhands.dev` 官方文档、PyPI API 与 arXiv 论文;由四个并行子代理分别覆盖架构/事件流、沙箱运行时、上下文/技能/人机协同、UI/产品面。
- 调研快照:2026-10-26。文中版本号(stars 91.9k、Canvas v1.33.0、SDK 1.58.2)为当日快照。
- 组织已由 `All-Hands-AI` 改名 `OpenHands`(旧 URL 重定向),文档域名 `docs.all-hands.dev` 308 跳转至 `docs.openhands.dev`;引用旧资料时需注意代际。
- 各子代理明确标注的不确定项在下文以〔不确定〕注明;未标注者为源码或官方文档直接可验证。
- 本地对照基线:`PROJECT_BASIS.md`、`docs-site/docs/architecture.md`、`src/ainrf/harness_engine/`、`prompts/mode1-discovery.md` / `mode2-reproduction.md` 与 2026-09/10 worklog 中记录的痛点。

## 2. 2026 年的 OpenHands 全景

重组后的仓库地图(均属 `OpenHands/` 组织):

| 仓库 | 角色 | 许可 |
| --- | --- | --- |
| `OpenHands` | 主仓库,main 分支已是纯 TS 应用 "Agent Canvas"(v1.33.0):自托管 coding agent 控制中心,除自带 agent 外经 ACP 接入 Claude Code、Codex、Gemini CLI、Pi、OpenCode | MIT |
| `software-agent-sdk` | V1 SDK monorepo:`openhands-sdk`(Agent/Conversation/LLM/事件/安全/skills)、`openhands-tools`(terminal/file_editor/browser/task_tracker 等)、`openhands-workspace`(Local/Docker/Remote/K8s/Apptainer)、`openhands-agent-server`(多会话 REST+WS 服务)+ TS 客户端;PyPI 1.58.2(2026-10-25) | MIT |
| `automation` | 调度与事件触发的自动化服务 | — |
| `benchmarks` | 评测(SWE-Bench、SWE-Bench Pro、GAIA、Commit0、OpenAgentSafety、ProgramBench) | — |
| `OpenHands-CLI` | V1 CLI,已停止积极维护,README 指向 Canvas | — |
| `sandbox-server` | 社区沙箱控制面(Docker/K8s/Remote/Local) | — |
| `OpenHands-Cloud` | Cloud 控制面的 Helm charts | PolyForm Free Trial(非开源) |
| `legacy` + 主仓库 0.4.0–0.62.0 tags | V0 Python 单仓快照(考古用) | — |

V0 的 `openhands/` Python 后端、`AgentDelegateAction`/`RecallAction` 事件、`DockerRuntime/RemoteRuntime/E2BRuntime` runtime 类族、IPython 工具、PySocks 代理防护均只存在于历史 tag,main 上已删除。V1 官方论文(*The OpenHands Software Agent SDK*,arXiv:2511.03690,MLSys 2026)称 V1 为完整架构重设计,事件溯源开销可忽略、系统可归因故障显著下降。

## 3. V1 SDK 核心架构

### 3.1 事件模型与持久化

- 事件是不可变 Pydantic 模型(`openhands/sdk/event/`):`MessageEvent`、`ActionEvent`、`ObservationEvent`、`SystemPromptEvent`、`Condensation`(压缩结果)、`PauseEvent`、`ConversationErrorEvent` 等;共享同一 `llm_response_id` 的多个 `ActionEvent` 在送 LLM 时合并为一条多 tool_call 消息(并行工具调用)。
- 持久化是**纯文件 JSON,不是 SQLite**:每会话一个目录(`base_state.json` + `events/event-NNNNN-<id>.json`);agent 对象本身序列化进 `base_state.json` 用于恢复;恢复 = 加载状态 + 重放事件。追加式事件日志同时充当 agent 记忆与集成点。
- 无 "Recall" 事件、无 `AgentLoop` 类、无 `AgentHub` 类——这些是 V0 概念或提问时的误称。

### 3.2 Agent Server 与会话控制

- 沙箱内跑 `openhands-agent-server`(FastAPI):REST 为主,事件流走 **WebSocket `/sockets/events/{conversation_id}`**——首帧 `{type: auth, session_api_key}` 认证,推送支持流式 token delta,断线重连支持 **`resend_mode=all | since&after_timestamp=…`**;另有 `/sockets/bash-events` 推终端事件。
- 会话控制端点:`run / pause / interrupt / fork / navigate / children`;`pause` 写 `PauseEvent` 并跑完当前步,`interrupt` 立即取消在途调用并为未完成工具调用补合成 `AgentErrorEvent` 保持历史可恢复。
- **消息排队**:运行中以 `run:false` 追加消息即排队,循环在步与步之间消费;新用户消息把 `finished/stuck` 重置回 `idle`;`max_iterations`(默认 500)按次 run 重新计数;卡死检测为连续 4 对相同 action/observation → `stuck`。
- **会话所有权 fencing(ConversationLease)**:文件租约 = owner + 单调递增 generation + TTL(默认 45s),同主机用 `os.kill(pid, 0)` 判死;接管方升 generation,写前校验租约否则抛 `ConversationOwnershipLostError` 防旧写者。
- 会话中途可 `switch_llm / switch_profile`(写入 `base_state.json` 跨重启生效,与 agent 同配置的 condenser 随之切换)。

### 3.3 Agent loop、LLM 与安全

- `Agent.step()` 单步原子模型:pending 确认动作 → condenser → LLM(超限发 `CondensationRequest`)→ 解析(tool calls → ActionEvent(s);纯文本 → MessageEvent)→ 确认门 → 执行工具出 ObservationEvent(s);由 Conversation 层持续调度。
- LLM 基于 LiteLLM(100+ 提供商,`provider/model` 命名),双路径 completion/responses,指数退避重试;metrics 含输入/输出/缓存 token、按请求成本、延迟,会话级 `accumulated_cost`。
- 安全分析器在动作执行前评级 LOW/MEDIUM/HIGH(实现:Pattern、LLM、PolicyRail、Ensemble 等);确认策略 `AlwaysConfirm / NeverConfirm / ConfirmRisky(threshold, confirm_unknown)`,默认 NeverConfirm;被扣留动作使会话进 `waiting_for_confirmation`(ActionEvent 已记录、命令未执行、不占 run 槽),应答走 `respond_to_confirmation`。
- 多智能体:TaskToolSet 子会话委派(默认同步阻塞,子会话持久化、可 `resume` 续跑);agent 注册表发现顺序 程序注册 > 插件 > 文件(`.agents/agents` > `~/.openhands/agents`);子 agent 继承父会话 MCP servers。

## 4. 沙箱与 workspace

- 现行体系没有 V0 的 runtime client/server 对:Agent Server 本身跑在沙箱内,客户端只收事件(`RemoteConversation` → `POST /api/conversations/{id}/run`)。
- workspace 实现:Local(无隔离)、Docker(预构建镜像 `ghcr.io/openhands/agent-server`)、Remote(连任意已运行 agent-server)、Apptainer(HPC)、Cloud、K8s `AgentSandbox`(CRD + `SandboxWarmPool` 亚秒级启动 + 可选 gVisor/Kata)。
- 沙箱内工具(`openhands-tools`):
  - `terminal`:**tmux 持久会话**,pane 池(默认 4)并行命令,PS1 嵌 JSON 捕获 exit_code/pid/cwd,无输出 30s 暂停询问,输出截断 30000 字符,`is_input` 可发 `C-c`/方向键等原始键;
  - `file_editor`:view/create/str_replace/insert/undo_edit;
  - `browser`:browser-use + Chromium(CDP),navigate/click/type/get_state/…,录屏为 rrweb DOM 事件 JSON;
  - 其他:task_tracker、apply_patch、glob/grep、子会话委派等。IPython/Jupyter 已退役,无内置 web search。
- 隔离:容器内非 root 用户 `openhands`(10001);full 镜像给该用户 sudo NOPASSWD;沙箱粒度由部署决定。开源 Docker 路径**不设 CPU/内存限额**(K8s 路径在 pod template 配)。
- **开源栈没有 checkpoint/restore**:对话 `fork` 只是事件级深拷贝(可按事件截断,不回滚文件系统);docker-commit 式快照仅存在于商业云(前端注释与论文侧证,未开源)〔不确定:云侧细节〕。
- 文件管理:upload/download/目录 tar 归档,直接操作沙箱 FS 不做同步;Trash 原子改名 + 三级存储回收(CACHES→DEPENDENCIES→RUNTIME);VSCode 经 openvscode-server(8001 端口 + connection token)。

## 5. 上下文压缩、技能与人机协同

- **Condenser**:压缩以 `Condensation` 事件持久化进事件日志(类比 Cassandra/Kafka tombstone):`forgotten_event_ids` + `summary` + `summary_offset`,下一步 `View.from_events()` 据此过滤;摘要可滚动叠加。`LLMSummarizingCondenser` 默认 max_size=240 事件(工厂默认 80)、keep_first=2/4;触发分 SOFT(事件数启发式,可重试)与 HARD(token 超限/显式请求,失败回落 hard_context_reset)。V0 的十种 condenser 只保留 llm_summarizing/no_op/pipeline 三种。
- **Skills**:正名迁到 Agent Skills 规范 `.agents/skills/<name>/SKILL.md`(遗留 `.openhands/skills|microagents` 兼容,project > user > public)。**渐进披露**:系统提示只渲染 `<available_skills>` 的 name+description(刻意隐藏磁盘位置),完整内容由内置 `invoke_skill` 工具按名加载;三类触发器:keyword(整词、大小写不敏感)、path(gitignore 风格 glob,首触注入一次)、task(`/name` + `${var}` 输入);`AGENTS.md` 作为常驻技能全文进 system prompt;marketplace 可安装。
- **Prompt 组织**:PromptRegistry 有序段(static 19 段 + dynamic 段),按 `cache_tier` 分桶,volatile 值(DateTime)刻意放最后保缓存友好;`SOUL.md` persona 覆盖。
- **跨会话记忆**:两层 Markdown(`~/.openhands/memory/` + workspace `.openhands/memory/`),各含 MEMORY.md 索引 + 日期日志;启动时注入 system prompt,总预算 6000 字符;无专门写入工具,靠系统提示指示 agent 用文件工具自维护;无向量检索。

## 6. 产品面

- **Canvas UI**:chat(composer 显示 live-activity chip、失败 Retry/Dismiss)、文件树 + diff viewer、Overview/git 面板(commits 抽屉)、终端、浏览器视图(rrweb 录制)、"Branch from here" 任意消息分叉、`/goal` 目标循环(agent+judge)、语音输入、转写导出、Automate 页、Backends 切换(local/Docker/VM/K8s/Modal/Cloud)、composer 的 **context meter**(token 用量 + Compact context 入口)。
- **自动化**:定时 prompt/plugin 运行(每次全新沙箱);预置 issue→PR(GitHub/GitLab/Jira/Linear,`openhands` 标签,默认 draft PR);事件驱动 webhook 需可达 VM 或 Cloud。
- **多用户**:开源版**无 auth/RBAC/多用户/隔离沙箱**(默认仅 loopback,单开发者定位);多用户、SAML、审计、预算在商业 Cloud/Enterprise(Keycloak);`OpenHands-Cloud` Helm 为 PolyForm Free Trial 试用许可。
- **可观测**:OTel 经环境变量开启(Laminar 插桩,span 层级 conversation→run→step→llm/tool);LLM metrics(成本/token/延迟/缓存)入会话统计。

## 7. 与 OpenScience 的逐项对照

我们的取向:`harness_engine` 把 agent brain 委托给外部 harness(claude-code、codex-app-server),自己拥有 Conversation Domain(Task/Turn/Item/Submission/RuntimeExecution/Binding,SQLite 事务+幂等+因果 guard)、多租户 Linux 隔离、literature 领域与 WebUI。OpenHands V1 自研 loop + 沙箱,Canvas 又同时编排外部 agent——两边在"编排外部 harness"上殊途同归。

### A. 直接命中我们已记录缺口(优先参考)

1. **任务详情页流式输出**。2026-09-23 worklog 已记录"消息无轮询/流式,运行中输出需重进页面"。OpenHands 的 `/sockets/events/{id}` 是成熟参考:首帧 auth、流式 delta、**断线 `resend_mode=since&after_timestamp` 补发**。我们已有 WS 基建(terminal attachments)与 EngineEvent→TurnItem 持久化通路,缺的只是面向前端的订阅通道与重放语义——这是最可直接落地的一项。
2. **Dispatcher 可靠性与重试上限**。同期记录"确定性派发失败无重试上限"(曾致两任务交替饥饿)。OpenHands 的 ConversationLease(owner+单调 generation+TTL+`os.kill(pid,0)`+写前 fencing)与我们 RuntimeProbe 的 UNKNOWN/ABSENT 语义和 adopt_runtime 面向同一问题,其 fencing 校验是值得对照的实现。
3. **"活着但空转"的更早止损**。我们的 engine_inactivity_timeout 只能判死;OpenHands 的 stuck 检测(连续 4 对相同 action/observation)+terminal 30s 无输出暂停询问,提供了进程级与语义级两层信号。

### B. 值得评估对齐的开放标准(借标准,非借代码)

4. **ACP(Agent Client Protocol)**。Canvas 经 ACP 接 Claude Code/Codex/Gemini CLI;我们是两个 bespoke adapter(`claude_code.py`、`codex_app_server.py`)。若 ACP 对长任务、审批、附件的覆盖度足够,对齐可摊薄适配器维护并免费获得更多引擎。需专项评估,不在本调研下结论。
5. **Agent Skills 规范**。我们的 skills 模块(discovery/loader/mount/registry_sync)可与 `.agents/skills/SKILL.md` 对齐(claude-code 原生支持该格式);OpenHands 的渐进披露(系统提示只列 name+description)与 **path/task 触发器**是具体能力差距点。

### C. 方向互证(它走到了和我们相同的结论)

6. Canvas 同时支持自带 agent 与外部 coding agent——印证 harness_engine 的编排取向;它保留自研 loop 的理由(确认门、压缩、fork、暂停粒度)也正是委托 harness 后能力面受限的地方,属于应显式记录的 trade-off。
7. pause(跑完当前步)vs interrupt(取消在途+合成错误事件保持历史可恢复)、运行中消息排队步间消费——与我们 interrupt / `retry_of_turn_id` / TurnSubmission 排队语义同构;interrupt 补合成错误事件的细节可与我们的 backfill 逻辑对照。
8. 事件级 fork+UI 分叉 vs 我们的 fork-preview+confirm:我们更严谨(预览、显式确认、canonical summary),无需改动。

### D. OpenScience 领先、无需借鉴

9. 多租户隔离(auth/RBAC/Linux 用户隔离/配额):OpenHands 开源版完全没有(单用户 loopback),多用户是商业版能力。
10. 领域深度:literature tracking、project/workspace/environment 模型、SQLite 事务化的 durable Task 生命周期,均超出其范围(其为纯文件 JSON 持久化,单会话目录所有权模型)。
11. 发布纪律:release manifest/备份恢复验证/维护窗口 runbook 对其开源栈无对应物。

### E. 它有但不建议引入

12. 自研 agent loop+工具集:与委托 harness 架构冲突;仅当需要 harness 给不了的确认门/压缩控制时重估。
13. K8s warm pool/gVisor、沙箱内 agent-server:实验室内部部署模型(PROJECT_BASIS)不需要;Apptainer 仅当算力环境迁入 HPC 再看。
14. checkpoint/restore:开源栈不存在(商业云才有 docker-commit 式);mode2 复现实验的快照需求不能从这里借,应另立项(workspace 级 git tag 或 volume snapshot)。
15. 浏览器工具(browser-use):mode1 目前靠 harness 的 WebSearch/WebFetch 足够;JS 重/登录墙站点成为实际瓶颈时再立项。
16. rrweb 录制、语音输入、VSCode-in-sandbox:产品加分项,非当前需求。

## 8. 结论

用户直觉"它实现了我们需要的一些功能"成立,但具体清单比想象窄而深:真正需要的是**事件流通道(含断线重放)**与**dispatcher 租约 fencing** 两个已记录痛点的参考实现,外加 **ACP** 与 **Agent Skills 规范**两个对齐机会;其余多数能力要么我们已有对等物,要么不符合我们的架构与部署边界。

## 9. 主要来源

- 主仓库与组织:https://github.com/OpenHands/OpenHands (经 https://github.com/All-Hands-AI/OpenHands 重定向)、https://api.github.com/repos/OpenHands/OpenHands/contents/
- V1 SDK:https://github.com/OpenHands/software-agent-sdk (`openhands/sdk/event/`、`conversation/state.py`、`conversation_lease.py`、`context/condenser/`、`skills/`、`security/`;`openhands-agent-server/sockets.py`、`conversation_router.py`;`openhands-workspace/openhands/workspace/`)
- 文档站:https://docs.openhands.dev (sdk/arch/events.md、convo-persistence.md、convo-pause-and-resume.md、agent-server overview、overview/skills、enterprise/enterprise-vs-oss.md 等;旧域 docs.all-hands.dev 308 跳转)
- 论文:https://arxiv.org/abs/2511.03690 (The OpenHands Software Agent SDK, MLSys 2026)
- 周边仓库:https://github.com/OpenHands/benchmarks 、https://github.com/OpenHands/automation 、https://github.com/OpenHands/sandbox-server 、https://github.com/OpenHands/OpenHands-Cloud
- V0 历史:主仓库 tags 0.4.0–0.62.0、https://github.com/OpenHands/legacy
