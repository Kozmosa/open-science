---
aliases:
  - 项目考古与诊断报告
  - Project Archaeology & Diagnosis
tags:
  - llm-working
  - archaeology
  - diagnosis
  - retrospective
  - ainrf
source_repo: scholar-agent
last_local_commit: workspace aggregate
doc_nature: llm-authored-analysis
---
# Scholar-Agent / AINRF 项目考古与诊断报告

> 把 `docs/LLM-Working/worklog/` 下 32 篇逐日工作日志（2026-03-14 → 2026-06-13）与 718 条 git 提交记录交叉阅读，做一次系统性的技术考古。目标不是情绪复盘，而是**把代价高昂的重复模式识别出来，转成可操作的工程建议**。

- **数据来源**：`docs/LLM-Working/worklog/*.md`（32 篇，1148 行）、`git log`（718 commits，单人 Kozmosa）、`PROJECT_BASIS.md` / `AGENTS.md` / `dev-bitter-lesson.md` / `docs/archive/legacy-v1-summary.md`、`docs/superpowers/specs/`（约 50 份设计稿）。
- **方法**：日志提供"为什么改/改了什么/验证结果"的叙事，git 提供提交类型分布、文件 churn、修复簇、节奏等硬数据；两者交叉印证后才下结论。

---

## 0. 一句话结论

> 这个项目在 3 个月里经历了**一次完整的"建大→删光→重建"循环**，并且在重建后又**重复了一次子系统级改名/重构**；表面问题是 bug 多，**根因是验证停留在"逻辑正确"层，没有覆盖"契约正确"和"系统正确"层**——表现为 `fix:feat = 0.86`、`test:feat = 0.10`，以及一连串"单测全绿 → 推 staging 直接 500 / 24 小时内内存爆炸"的事件。

---

## 1. 关键数字（硬数据）

| 指标 | 数值 | 解读 |
|------|------|------|
| 总提交 | 718（92 天） | 节奏极快 |
| `feat` | 223（31.1%） | — |
| `fix` | 191（26.6%） | **fix:feat = 0.86**，成熟项目通常 0.2–0.4 |
| `docs` | 120（16.7%） | 文档投入异常高 |
| `test` | 23（3.2%） | **test:feat = 0.10**，且多数是"迁移/恢复"而非新增覆盖 |
| 单日最高提交 | 50（05-07） | 爆发日 |
| 15+ 提交的爆发日 | 19 天 | 节奏不均匀 |
| 文档平台迁移 | 3 次 | MkDocs → GitHub Pages → Astro/Starlight |
| 被改最多次的文件 | `frontend/src/i18n/messages.ts`（73 次） | 国际化成了 churn 黑洞 |
| 最 fix-prone 的文件 | `deploy/Dockerfile`（31 次提交里 15 次是 fix = 48%） | 部署链脆弱 |
| 最长的修复链 | Terminal/PTY/tmux（60 天 16 次 fix） | 持续维修 2 个月 |
| docs/ 相关提交 | 257（35.7%） | 文档与代码几乎等比重 |

---

## 2. 演化纪年：项目的七个纪元

把日志和 git 叠在一起看，项目演化可以被切成 7 段。**理解这段弧线是理解一切冗余的前提**——很多"重复劳动"不是粗心，而是叙事方向多次急转弯的后果。

### 纪元 0 · 笔记仓库起点（≤ 2026-03-14）
仓库最初是 `scholar-agent-notes`——研究笔记 + 外部项目调研（`docs/archive/projects/`、`ref-repos/`）。产品叙事尚未成型。

### 纪元 1 · V1 编排器大建设（2026-03-14 → 03-26，49 commits）
**全仓最有规划感的一段**。围绕"P1–P9 + W1–W3"分阶段计划，TDD 严格推进：

- P2 MinerU 解析、P3 artifact+state store、P4 FastAPI+鉴权、P5 human gate+webhook、P6 SSE 事件层、P7 引擎+ClaudeCodeAdapter、P8 实验闭环+偏差诊断、P9 Mode1 文献发现闭环。
- 同期 W1–W3 落地 Gradio WebUI 工作台。
- 3 月 16 日单日把 `pytest tests/` 从起步推到 **105 passed**，每一步都先红后绿。
- **特征**：过度完整。`docs/archive/legacy-v1-summary.md` 后来承认，这是一套"bounded-autonomous orchestrator"的野心叙事。

> ⚠️ 这一阶段产出的 `src/ainrf/{agents,artifacts,gates,events,engine,parsing,state,webui}` 几乎全部在纪元 3 被删除。**这是本项目最大的一次沉没成本。**

### 纪元 2 · 转向规划（2026-04-04，纯文档日）
单日 8 条 `docs:` 提交，写出一整套 `refactoring-plan/`：把主叙事从"完整研究平台"收敛为**"单用户优先、task-centric、dashboard-first"**。这是项目第一次主动收缩。

### 纪元 3 · 清理 / 删除（2026-04-12 → 04-13，破坏性）
**最戏剧化的一天**。`2026-04-12` 两条 changelog 直接删除了纪元 1 的几乎全部成果：

- 后端：删 `agents / artifacts / gates / events / parsing / webui / agent / state` 子系统，只保留 `serve / container add / health / API key 中间件 / SSH 健康检查`。
- 前端：删任务页/任务详情页/工件组件，Dashboard 收缩成"最小健康壳"。
- worktree 分支名 `ainrf-cleanup-realignment`、`agent-ad136b29` 直接泄进日志。

> 考古判断：这不是"重构"，是**推倒**。`legacy-v1-summary.md` 把它定性为"cleanup-first realignment"。代价是：**之后所有 task 运行时能力都要从零重建**。

### 纪元 4 · 以 Terminal 为中心重建（2026-04-13 → 04-23，~100 commits）
删完之后，产品重新围绕**"web 终端 + 环境 + 工作区"**长出来：

- Web 终端：`ttyd/iframe`（04-13）→ 一周内整个迁移到 `xterm.js + PTY/WebSocket`（04-21），并立即进入 2 个月修复期。
- 环境控制面：`/environments` CRUD、检测、localhost 种子。
- code-server 受管嵌入 + 安装器（04-28）。
- Settings 页（04-23）。
- **Task Harness v1**（04-23）：webterm-keepalive 4 个 slice 演化出来的任务终端/takeover/archive 生命周期，**标志 task 运行时能力"复活"**——但它和纪元 1 被删的 TaskEngine 已经是两套完全不同的设计。

### 纪元 5 · 多引擎 + 控制面扩张（2026-04-27 → 05-25，~300 commits）
项目进入"功能大爆发"，也是 review-fix 循环最密集的阶段：

- **三个执行引擎**逐个接入：`claude-code`（原生）→ `agent-sdk`（05-06 起）→ `codex-app-server`（05-12）。每个引擎都要补 create/pause/resume/send-prompt/cancel/checkpoint。
- Skills 注入体系（`SkillInjectionService`，05-06）。
- Project Canvas（React Flow，05-07）。
- Auth/JWT + 资源所有权（05-18）。
- 文献追踪器（05-24）。
- **PR #37 的 review-fix 风暴**：18 条 → 21 条 → "Round 2" 9 条，几乎全是并发/状态机/schema 问题。
- 后端测试从 84（04 月初）一路涨到 **362**（05-09）。

### 纪元 6 · AgenticResearcher 重构（2026-06-03，单日 7 阶段）
**第二次子系统级改名/重写**。把 `task_harness/` 重构为 `harness_engine/`（执行引擎抽象）+ `agentic_researcher/`（任务管理门面），三个引擎统一到 `start/emit + pause/resume/send_input/cancel` 协议。

- 单日 7 个阶段一口气走完，测试到 389。
- **代价**：06-04 一整天是"restore 集群"——26 个提交里至少 10 个是 `restore ...` / `fix ...`，把前一天重构打坏的 task 预设、绑定选择器、E2E、admin 可见性一个个补回来。

### 纪元 7 · 生产加固 + 多租户（2026-06-05 → 06-13，~200 commits）
最近的冲刺：多租户 Linux 用户隔离（3 phase）、生产 Docker 部署、staging 环境、Prometheus/Grafana 可观测、部署版本、task retry。

- **多租户**：3 phase（06-11）每个 phase 后立刻跟同日/次日权限 fix（`sudo -u`、MCP config world-readable、EPERM）。
- **部署链**：06-06 一整天 9 个 Docker mirror/port/healthcheck fix；06-13 staging 建好当天就因端口冲突连修 2 次。
- **task retry**：06-03 引入 → 06-12 "so it actually executes" → 06-13 整个 redesign + 3 个 follow-up fix。**到日志截止日仍未收敛。**

---

## 3. 开发流程 / 工作流的演变轨迹

工作流本身在这 3 个月里也演化了，有几条清晰可见的轨迹：

### 3.1 日志纪律：从流水账到 changelog，再到"未来不回写"
- **03-15**：建立 worklog 规范，初版是"每个关键动作一条"。
- **03-16 11:05**：第一次自我修正——改成"每个已完成修改计划/工作批次追加一条 changelog"，并确立 **future-only 约定**（旧规则残留只在历史示例，不回写）。这是项目里少见的、很成熟的元规则。
- **05-26**：把 `CLAUDE.md` 收口成指向 `AGENTS.md` 的最小入口，确立**单一事实来源**；并把提交粒度细化为"worklog 随功能提交、根级约束文件独立提交"。

> ✅ **这是项目最强的工程实践**。正因为 changelog 足够精确，本次考古才可能可靠。多数仓库做不到这个粒度。

### 3.2 文档治理：三易其平台
- MkDocs（03-15）→ 抛弃 → GitHub Pages（05-29）→ Astro/Starlight（06-13，当天删掉旧 MkDocs 基建）。
- `docs/ainrf/` → 迁移 → 删除；`.rules/` 渐进披露（06-13）从 AGENTS.md 抽出低频内容。
- `AGENTS.md` 被提交 **25 次**，是 churn 第 20 名的文件。
- **判断**：治理方向是对的（progressive disclosure、single source of truth），但**平台层反复迁移消耗了相当多的提交**，且每次迁移都伴随一次"清理过时文档"。

### 3.3 验证流程：始终是"单测先行，但停在逻辑层"
- TDD 痕迹贯穿全程（大量"先红后绿"changelog）。
- 但**真正覆盖到 HTTP 响应序列化 / 真实引擎 / 真实部署的验证一直是缺位的**，靠的是"推到 staging 用真实请求跑一遍"这种事后救火（见 `dev-bitter-lesson.md` §11）。
- flaky test 被制度化地容忍：日志里反复出现"除已有失败的 X""pre-existing flaky"，最后一天还出现"误判为机器特定路径，实际是集成未接线"（06-12 22:40）。

### 3.4 分支/Worktree 卫生：爆发后清理
- worktree-first 范式被写进约束（05-26）。
- 但 04-24 一次清理就删了 **46 个分支**（11 已合并 + 2 worktree + 20 过时 worktree + 15 远程 topic），还保留 19 个 dirty worktree。
- **判断**：worktree-first 没问题，但缺乏自动清理，导致周期性大扫除；且 worktree 绝对路径频繁泄进 worklog。

---

## 4. 诊断：冗余点与阻塞点

把"重复付出"和"卡住推进"按主题归类。每条都给**证据**（commit / 日志）和**代价估计**。

### 4.1 🔴【头号冗余】"建大 → 删光 → 重建"循环
**同一类能力被实现三次**：

| 能力 | 第 1 版（被删） | 第 2 版 | 第 3 版（当前） |
|------|----------------|---------|----------------|
| 任务运行时 | `ainrf.engine` + `TaskEngine` + orchestrator（纪元 1，03-16）→ 04-12 删除 | `task_harness/` + Task Harness v1（04-23） | `agentic_researcher/` + `harness_engine/`（06-03） |
| 任务状态机 | artifact lifecycle + state store（03-16） | `queued/starting/running/succeeded/failed`（04-23） | 同左 + `paused`，protocol 统一 |
| Web 前端 | Gradio WebUI W1–W3（03-16）→ 删除 | React + Vite 最小壳（04-13） | 当前 React 全功能 WebUI |

- **代价**：纪元 1 的 ~9 个子系统 + Gradio 前端几乎全部沉没；纪元 4–6 把 task 运行时又重做了两遍。
- **根因**：纪元 1 是"过度完整的未来态蓝图"，与现实单用户需求脱节，触发推倒重来；之后每版都偏"够用就行"，但缺乏**被保护的 durable contract**，于是又会被下一次重构推翻。

### 4.2 🔴【头号阻塞】验证只到逻辑层，不到契约/系统层
这是 `fix:feat = 0.86` 的真正解释。三类反复出现的 bug，**单测全部拦不住**：

**A. 响应 schema 的可选性与序列化**
- `TaskRetryResponse.archived_task_id` 非可选 → 新逻辑传 `None` → Pydantic v2 严格拒绝 → staging 直接 500（`4c737a8`，`dev-bitter-lesson.md` §11）。
- 资源监控页前后端 **camelCase vs snake_case** 不匹配，所有数据 `undefined`（05-06 PR review，critical）。
- `/auth/me` 500：`must_change_password` 没加进 `UserInfoResponse`（05-19）。
- 结构：**测试只验证 service 层返回的 `Task` 对象，从不经过真实 HTTP 响应序列化**。

**B. 日志层 kwargs 混用**
- stdlib `logging.getLogger()` 被传 structlog 风格 kwargs → `TypeError` → 被任务循环吞成 FAILED → task 永久卡死（`2d03659`，`dev-bitter-lesson.md` §12）。

**C. 并发与状态生命周期**
- seq 竞争（emit 与 send_prompt 跨连接）→ 改 `isolation_level="IMMEDIATE"`（05-08 comprehensive review）。
- sticky pause（pause flag 没清）→ 重置 `should_pause_after_turn`（05-08）。
- `error flag` 跨 turn 残留（05-08）。
- **EventSource 泄漏**：`openStream()` 创建的 source 没赋给 ref，cleanup 永远 close 不到旧 stream → 任务切换串台（06-12 22:40，正是 bitter lesson §8 的同类病根）。
- 任务输出**跨任务串污染**：8 天 4 个 fix（`9425ee8` → `bba9b17` → `c538743`）才收敛。

> **共同病根**：这些 bug 都不是"逻辑写错"，而是"逻辑对了，但与系统边界（HTTP 序列化 / 进程并发 / 事件生命周期）的契约没被验证"。单测的断言对象错了。

### 4.3 🟠 三个执行引擎 = 3 倍生命周期维护面
`claude-code` / `agent-sdk` / `codex-app-server` 三个引擎，每个都要独立实现 create/pause/resume/send-prompt/cancel/checkpoint/token 汇总。后果：

- agent-sdk engine 的 review-fix 风暴（PR #37：session 状态机、checkpoint 路径、seq 竞争、pause 窗口期……）。
- codex-app-server engine：`CODEX_HOME` 隔离、app-server 提前 EOF 卡死、user echo 去重、初始 prompt 未落库（05-12、06-04）。
- 06-03 把协议统一成 `start/emit + ...` 本是想消除这个 3 倍面，但属于"事后收敛"而非"事前契约"。

### 4.4 🟠 环境与部署链是脆弱的"隐藏产品"
整条部署链反复消耗整天：

- **前端"双源"**：nginx 服务宿主机 `frontend/dist` 而非容器内产物 → 改了代码但 UI 没变（`dev-bitter-lesson.md` §1，被写成头号硬规则）。
- **Docker mirror 日**：06-06 一天 9 个 fix（1ms.run / USTC / aliyun 镜像、Node 升 24、`HOME=/opt/ainrf`、host networking、health 200 vs 503）。
- **端口冲突**：8000 被占 → 内部用 18000（06-11）；staging 与生产 sshd 端口冲突（06-13）。
- **多租户权限**：`sudo -u` vs `setuid` vs `subprocess.Popen(user=)`（`dev-bitter-lesson.md` §3）；MCP config 必须 world-readable；tenant 目录必须 tenant 用户建。
- **部署版本**：先 unify（06-12），次日又 split 成前后端独立版本（06-13）。

> 结构性问题：**环境是产品的一部分，却被当作事后项**。每次"部署/多租户"类问题都是发现后才修，没有一个"干净环境起一次完整 round-trip"的闸门。

### 4.5 🟠 i18n 成了 churn 黑洞
`frontend/src/i18n/messages.ts` **73 次提交，全仓第一**。05-22 单日 8 个 i18n fix（双语支持 4-21 加的，一个月后才发现大量漏翻 + 大括号没配平 + key 路径错）。i18n 没有覆盖率守卫，靠人工扫描 + 整天补漏。

### 4.6 🟡 文档与治理 thrash
- 3 次文档平台迁移（每次都伴随"删过时内容"）。
- `AGENTS.md` / `CLAUDE.md` / `PROJECT_BASIS.md` 反复对齐叙事、补规则（25 + 9 + 多次）。
- 包名 `scholar-agent-notes` → `ainrf`（04-23）。
- **判断**：治理意图良好（progressive disclosure、single source），但**平台层和入口层反复搬家**，吃掉了一大批本可以写代码的提交。

### 4.7 🟡 flaky test 被制度化容忍
日志里反复出现"除已有失败的 X""pre-existing flaky""9 pre-existing failures（其中 4 个其实是真失败）"。06-12 的考古性发现最具代表性：**被标注成"机器特定路径"的失败，实际是集成根本没接线**（workspace file link util 零调用方）。容忍 flaky = 放过真实回归。

---

## 5. 根因综合：为什么这些模式会反复出现

把上面 7 条收口成 5 个**系统性根因**。每条都同时解释了"为什么单测拦不住"和"为什么同样的坑会再踩"。

1. **验证层次错位**。`pytest` 验证"逻辑正确"，但生产 bug 集中在"契约正确"（schema 可选性/序列化）和"系统正确"（并发/生命周期/部署）。缺一层 **契约测试 + 集成冒烟**。→ 解释 4.2 全部。
2. **durable contract 缺位**。没有一份"被保护的、跨重构存活的 task 模型契约"，于是子系统可以整体改名/重写（纪元 1/4/6），每次重写都重付 lifecycle 的学费。→ 解释 4.1。
3. **纵向加功能、横向不加固**。三个引擎一个个加，每个引擎独立修 lifecycle bug，而不是先固化一个引擎契约再复用。→ 解释 4.3；也解释了 review-fix 风暴。
4. **环境不是一等公民**。部署/多租户/权限/镜像总在功能之后才被触及，没有"干净环境 round-trip"闸门。→ 解释 4.4。
5. **单人高速节奏 + 无 merge gate**。19 个 15+ 提交的爆发日，与修复簇高度相关；功能"绿了就推"，没有"必须过 review / 必须真请求触发条件分支"的强制门。→ 解释整体高 fix:feat。

> 一句话：**这个项目不缺工程纪律（TDD、worklog、bitter lesson 都做得很好），缺的是"验证闸门"和"契约护栏"**——纪律用在写代码上，没用在"代码与系统边界是否对齐"上。

---

## 6. 值得保留的正面实践（别在整改时丢掉）

考古不能只挖问题。以下实践是**真资产**，整改时应保护：

- **worklog changelog 纪律 + future-only 约定**（3-16）——本报告之所以可靠，全靠它。继续保持。
- **`dev-bitter-lesson.md`**——把高代价经验蒸馏成检查清单（§1–§13），是非常成熟的实践，且持续在追加（06-12 补 §8/§9/§10）。这是项目最该被外部学习的产物。
- **TDD 先红后绿**——贯穿全程，证据扎实。
- **staging 环境（06-13）**——虽然建得晚、当天还修了端口冲突，但它正是 4.2 所缺的那层验证基础设施。
- **`.rules/` 渐进披露 + AGENTS.md 单一事实来源（05-26/06-13）**——治理方向正确。
- **诚实的研究闭环**——并行跑的 Mode1（FedST → partition-first FL）在拿到真实数据负结果后，敢于下调结论到 "negative result, stop"（04-22/04-23），没有硬撑。这是难得的科研诚实。
- **测试体量真实增长**：后端 84 → 505，前端到 188，不是装饰性数字。

---

## 7. 洞察与建议（按 ROI 排序）

建议尽量"复用已有基建"，而非引入新流程。

### 🥇 P0 · 补一层"契约/序列化"测试（最高 ROI）
针对**头号缺陷类**（4.2A）：

- 对每个 Pydantic 响应模型，加一个**往返测试**：构造 service 返回 → 真实经过 `FastAPI` 响应序列化 → 断言字段存在 + `snake_case` + 可空字段能传 `None`。
- 行为从"必然产生 X"变成"条件性产生 X"时，**强制审计 response schema 可选性**（已写进 `dev-bitter-lesson.md` §11，但没有测试兜底）。
- 预期：直接消灭 `/auth/me 500`、`TaskRetryResponse` 500、资源监控 `undefined` 这一整族。
- 成本：低，纯 pytest，针对 `schemas.py`（已被改 60 次，churn 第 2 名，最该有护栏）。

### 🥇 P0 · 把 staging round-trip 做成 merge gate
针对**验证层次错位**（根因 1）+ 部署脆弱（4.4）：

- staging 已经存在（06-13）。要求：**每个新增/改动的 API 路由，PR 里至少在 staging 跑一次能触发其条件分支的真实 HTTP 请求**（happy + 一个 error 分支）。
- 这正是 bitter lesson §11 反复呼吁的"完整链路验证不能只靠 pytest"。
- 成本：低（基建已有），收益：拦截 schema/部署/权限三类 bug。

### 🥈 P1 · 在加第 4 个引擎前，固化引擎契约 + 参数化测试
针对**三引擎 3 倍维护面**（4.3）：

- 写一套**针对抽象 `ExecutionEngine` 协议的参数化测试**（create/pause/resume/send-prompt/cancel/checkpoint/token），对 3 个现有引擎各跑一遍。
- 之后任何引擎 bug，修一次、三个引擎同时受益；新增引擎必须先过这套契约。
- 06-03 的协议统一是正确方向，缺的就是这层"契约测试"。

### 🥈 P1 · 保护 task 模型 durable contract，停止子系统级改名
针对**建删循环**（4.1）：

- 把当前 `agentic_researcher` 的任务模型（字段、状态机、事件形状）**写成一份 spec + 一组不变量测试**，明确"这是跨重构不变的契约"。
- 之后再要重构，只允许"换实现、不换契约"，避免纪元 6 式的整块重写 + 整天 restore。

### 🥉 P2 · 清理环境验证 + 收编 Docker/端口类 fix
针对**部署链脆弱**（4.4）：

- 加一个 CI job：从零 `docker compose up` → 打 `/health` → 跑一个 task round-trip。
- 把"前端双源""端口冲突""镜像源"这些 bitter lesson 写进该 job 的断言，而不是写进人类记忆。
- 预期：消灭"一整天 9 个 mirror fix"这种整日消耗。

### 🥉 P2 · i18n 覆盖率守卫 + flaky-test 零容忍
针对 4.5 / 4.7：

- i18n：加一个静态检查，扫描组件里的硬编码用户可见字符串（项目已有 `messages.test.ts` 做 key parity，扩展成 fail-on-hardcode）。
- flaky：把"pre-existing failure"从宽限改成"必须开 issue 跟踪 + 7 天内修或 quarantine"，否则会继续掩盖真回归（如 06-12 的"零调用方"集成 bug）。

### 🥉 P3 · 冻结文档平台，节制治理 churn
针对 4.6：

- Astro/Starlight 已是第 3 个平台，**明确"无强制理由不再迁移"**。
- 把"清理过时文档"做成定期巡检（例如每月一次），而不是每次重构顺带做。
- `.rules/` 渐进披露是好实践，保留。

### 🥉 P3 · 给爆发日加轻量 review 门
针对根因 5：

- 50-commit 的爆发日与修复簇强相关。在合并前跑一次 code-review subagent（项目已有 `/code-review` skill），重点盯 schema 可选性、并发、日志 kwargs——这三类是 review 最容易抓到的。
- 不追求阻断，追求"在 merge 前暴露"，替代"推到 staging 才发现"。

---

## 8. 附：决策建议速查表

| 你正要做… | 先检查… | 关联根因 |
|-----------|---------|---------|
| 改某个行为从"必然有 X"→"条件性有 X" | 该字段在所有 response schema 里是否改成 `X \| None` + 加往返测试 | 4.2A |
| 加日志调用 | 该 logger 是 stdlib 还是 structlog？传参风格是否匹配 | 4.2B |
| 加/改 API 路由 | staging 真实 HTTP 请求触发条件分支跑过没 | 4.2 / 4.4 |
| 加第 4 个执行引擎 | 先过参数化引擎契约测试 | 4.3 |
| 改 task 模型 | 是否破坏 durable contract 不变量 | 4.1 |
| 改前端 | 浏览器加载的 bundle hash == 宿主机 dist hash？nginx 重启了？ | 4.4（§1） |
| 多租户/权限路径 | 文件谁建、谁读、跨用户边界是否 chmod/chown / `sudo -u` | 4.4（§2/§3） |
| 遇到 flaky test | 当成真 bug 查根因，别标 pre-existing 跳过 | 4.7 |

---

## 9. 收尾判断

如果只能做一件事，做 **P0 的契约/序列化测试 + staging round-trip merge gate**——它精准命中本仓库 3 个月里代价最高、出现最频繁的那一类 bug（schema/序列化/部署），而且基建（`schemas.py`、staging、pytest）都已就位，几乎不需要新引入任何东西。

这个项目的工程**下限很高**（TDD、worklog、bitter lesson、科研诚实都在线），**缺口集中在"验证闸门"和"契约护栏"这一层**。补上这一层，`fix:feat` 应能从 0.86 明显回落，"单测全绿却 staging 爆炸"的事件会大幅减少。

---

### 相关笔记
- [[dev-bitter-lesson]] —— 高代价坑的检查清单（本报告多次引用）
- [[archive/legacy-v1-summary]] —— 纪元 1→3 清理的官方定性
- [[worklog/2026-04-12]] —— 删除日
- [[worklog/2026-04-23]] —— Task Harness v1 复活
- [[worklog/2026-06-03]] —— AgenticResearcher 重构
- [[worklog/2026-06-04]] —— restore 集群
- [[worklog/2026-06-12]] —— bitter lesson 持续追加 + 部署版本
