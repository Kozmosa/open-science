---
aliases:
  - AINRF 领导汇报材料
  - 2026-04 Leadership Deck
tags:
  - ainrf
  - presentation
  - leadership
source_repo: scholar-agent
source_path: docs/ainrf/presentations/2026-04-leadership-deck/index.md
---

# AINRF 领导汇报材料

> [!abstract]
> 本页为 2026 年 4 月面向学院领导的 5–8 分钟汇报的事实主稿。所有主张均对应到仓库源码、测试或 worklog，不编造未交付能力。

---

## Slide 1 — 封面 / 一句话结论

**标题**：AINRF：Agent-Driven 科研控制面，减少重复劳动

**核心信息**：
- AINRF 不是"全自动科研替代者"，而是一个已经能落地减少科研重复劳动的 agent-driven research control plane。
- 当前已交付：CLI、FastAPI 后端、React WebUI，以及围绕 environment / workspace / terminal / task / code-server 的控制面与运行时能力。

**讲稿提示**（约 45 秒）：
> 各位领导好。AINRF 是我们团队正在推进的科研辅助基础设施。今天汇报的核心结论只有一句：我们不是在做"替代研究者的 AI"，而是在做一个能减少科研重复劳动的控制面——让研究者少花时间配环境、找入口、盯终端。

**证据来源**：
- `docs/ainrf/index.md`：当前产品面主入口
- `docs/framework/ai-native-research-framework.md`：项目定位与边界
- `README.md`：仓库当前主叙事

---

## Slide 2 — 为什么要做

**标题**：科研辅助中的四类时间浪费

**核心信息**：
1. **配环境**：新机器、新仓库、新依赖，反复踩坑
2. **找入口**：仓库结构复杂，找不到 baseline 运行命令
3. **复现 baseline**：论文代码跑不通，调试成本高
4. **人工值守长任务**：训练、网格搜索需要人盯着终端

**收束**：把人从低价值操作中解放出来，让研究者把精力集中在"提出问题和判断结果"上。

**讲稿提示**（约 60 秒）：
> 我们在日常科研和带学生过程中反复遇到四类浪费。第一类是配环境——新服务器、新仓库、新依赖，每次都要重新踩坑。第二类是找入口——一个开源仓库clone下来，不知道跑哪个文件、用什么命令。第三类是复现 baseline——论文代码往往跑不通，调试成本极高。第四类最隐性：长任务需要人盯着终端，生怕断掉。AINRF 的目标就是把这四类低价值操作的时间压到最低。

**证据来源**：
- `docs/framework/ai-native-research-framework.md`：当前定位强调"simple but genuinely helpful tool"
- `docs/LLM-Working/worklog/2026-04-23.md`：Task Harness v1 设计 spec 明确针对"人工值守"问题

---

## Slide 3 — 今天已经交付了什么

**标题**：已落地的产品面：CLI + API + WebUI

**核心信息**：
- `ainrf` CLI：可安装、可服务化、可初始化
- FastAPI 后端：已挂载 environments / projects / workspaces / terminal / tasks / code 路由
- React WebUI：Tasks / Workspaces / Settings / Terminal / Code-Server 页面已交付
- 运行时能力：environment 管理、workspace 绑定、personal terminal、Task Harness v1、workspace browser、settings baseline

**关键主张**：可启动、可观察、可回看——不讲未来态大愿景。

**讲稿提示**（约 70 秒）：
> 到今天为止，我们已经交付了三个层面的产品面。最底层是 ainrf CLI，可以安装、可以启动服务、可以初始化配置。中间层是 FastAPI 后端，已经挂了 environments、workspaces、terminal、tasks、code-server 等完整路由。最上层是 React WebUI，Tasks 页、Workspaces 页、Settings 页、Terminal 页、Code-Server 浏览器都已经可用。我们强调的是"可启动、可观察、可回看"，而不是画一个大愿景。

**证据来源**：
- `src/ainrf/api/app.py`：后端路由挂载（lines 11–17）
- `frontend/src/pages/TasksPage.tsx`、`SettingsPage.tsx`、`TerminalPage.tsx`、`WorkspacesPage.tsx`
- `tests/test_api_v1_routes.py`、`tests/test_api_tasks.py` 等：API 回归测试 124+ passed
- `docs/LLM-Working/worklog/2026-04-23.md`：settings page baseline、Terminal Bench 修复等交付记录

---

## Slide 4 — 远程服务 AI Agent 如何加速科研

**标题**：控制面链路：从 WebUI 发起，到远程环境执行，再到持久化回放

**核心信息**：
- 用户在 WebUI/CLI 选择 workspace + environment，输入任务描述
- 系统按五层 prompt 组合：global harness → workspace → environment → task_profile → task input
- 经本地或 SSH 远程环境启动 Claude Code 执行
- 输出经 SSE 流实时回传，并持久化到 SQLite，支持事后回放

**图示**：`assets/control-plane.mmd` — AINRF 控制面与远程执行链路图

**讲稿提示**（约 75 秒）：
> 这是整套汇报的核心价值页。用户在 WebUI 上选一个工作区、选一个环境，输入任务描述。系统会按五层 prompt 组合上下文：全局 harness、workspace 描述、environment 配置、task profile、最后是用户输入。然后系统会在本地或 SSH 远程服务器上启动 Claude Code 执行。执行过程中，输出通过 SSE 流实时回传到前端，同时全部写入 SQLite 持久化。这意味着即使浏览器关了，回来也能回放完整输出。我们把"人盯终端"变成了"可监控、可回放"。

**证据来源**：
- `src/ainrf/task_harness/prompting.py`：五层 prompt composition（GLOBAL_HARNESS_PROMPT + workspace + environment + task_profile + task_input）
- `src/ainrf/task_harness/launcher.py`：本地 / SSH 远程启动 Claude Code 链路
- `src/ainrf/api/routes/tasks.py`：SSE 流输出与 SQLite 持久化
- `tests/test_task_harness_service.py`：task harness 服务回归测试

---

## Slide 5 — 为什么比直接手工跑 Agent 更省时间

**标题**：四个具体节省

**核心信息**：
1. **`scripts/webui.sh` 一键联调**：前后端联合启动，降低启动摩擦
2. **seed workspace + environment profile + settings 默认值**：减少重复输入
3. **Task Harness 让长任务从"人盯终端"变成"可监控、可回放"**：SSE 流 + SQLite 持久化
4. **workspace browser（code-server）降低远程查文件/翻目录成本**：浏览器内直接浏览远程 workspace

**讲稿提示**（约 60 秒）：
> 可能有人会问：我自己开 Claude Code 不也能跑吗？差别在于四个具体节省。第一，webui.sh 一键拉起前后端，不用手动配端口、配代理。第二，workspace 和 environment 有 seed 配置和默认值，不用每次重新输入。第三，Task Harness 让长任务从"人盯终端"变成"可监控、可回放"，浏览器关了回来还能看。第四，内置的 workspace browser 让你在浏览器里直接翻远程目录，不用 SSH 进去找文件。

**证据来源**：
- `scripts/webui.sh`：一键联调入口
- `src/ainrf/workspaces/service.py`：seed workspace 与 repo 绑定逻辑
- `src/ainrf/environments/service.py`：environment profile、默认 localhost seed
- `src/ainrf/code_server.py`：workspace browser / code-server 受管会话
- `tests/test_webui_sh.py`：联调脚本回归测试

---

## Slide 6 — 正在推进的下一层能力：Skills + ARIS 基座

**标题**：Skills 能力层与 ARIS 基座：把高频 workflow 模块化

**核心信息**：
- **Skills 层目标**：把常见 research-dev workflow 模块化成 skill，进一步减少 baseline 复现、环境 bootstrap、git/worktree、repo ops 等重复人力
- **当前状态**：`research-dev` skills package 设计 spec 已完成（单 package、多子 skill 结构，含 `project-init`、`env-bootstrap`、`git-workflow`、`commit-style`、`repo-ops` 等子 skill）
- **ARIS 基座**：test/ 目录已完成 ARIS 探索实验，后续将接入作为 VSA（Virtual Research Assistant）基座之一
- **页面上必须标注**：当前仓库中 skills 层主要处于设计推进中，底层控制面已具备承载条件

**讲稿提示**（约 60 秒）：
> 最后汇报一下下一步方向。我们正在设计 skills 能力层，目标不是再造一个大而全的 orchestration，而是把常见的 research-dev workflow——比如项目初始化、环境 bootstrap、git workflow、代码规范检查——模块化成可复用的 skill。这样可以进一步减少 baseline 复现和文件定位的浪费。需要明确的是，这一层目前处于设计推进中，底层控制面已经具备承载条件。另外，我们在 test 目录已经完成了 ARIS 基座的探索实验，后续会将其接入作为 VSA 的核心能力之一。

**证据来源**：
- `docs/LLM-Working/worklog/2026-04-23.md`：`research-dev` skills package 设计 spec（02:10 changelog）
- `test/Mode1/`：ARIS 探索实验（idea discovery、partition-first federated traffic forecasting 等）
- `docs/projects/ai-research-skills.md`、`docs/projects/claude-scholar.md`：外部 skills 参考调研

---

## Slide 7 — 收尾 / 争取支持

**标题**：下一步：把 Skill 层、度量指标、真实科研场景试点接到现有控制面上

**核心信息**：
- 争取继续推进 demo / pilot / 产品化打磨支持
- 下一步具体落点：
  1. Skills 层落地到现有控制面
  2. 建立任务成功率、时间节省等度量指标
  3. 在真实科研场景（如交通联邦预测）做 pilot 验证
- 强调：我们不是要做一个"24x7 自治科研引擎"，而是做一个"真正有用的科研辅助工具"

**讲稿提示**（约 45 秒）：
> 最后，我们希望争取学院继续支持这个方向的 demo 和 pilot 打磨。下一步有三个具体落点：第一，把 skills 层真正接到现有控制面上；第二，建立可量化的度量指标，比如任务成功率、环境配置时间；第三，在我们已经探索的交通联邦预测等真实科研场景上做试点验证。我们的目标不是"24x7 自治科研引擎"，而是一个"真正有用的科研辅助工具"。谢谢各位领导。

**证据来源**：
- `docs/framework/ai-native-research-framework.md`："a simple but genuinely helpful tool"
- `test/Mode1/idea-stage/PARTITION_FIRST_PLAN.md`：真实科研场景 pilot 方向

---

## Appendix — Claim-to-Evidence 对照表

| 页码 | 关键主张 | 证据文件 | 证据类型 |
|------|---------|---------|---------|
| Slide 3 | CLI + API + WebUI 已交付 | `src/ainrf/api/app.py`、`frontend/src/pages/*.tsx` | 源码 |
| Slide 3 | 124+ 测试通过 | `tests/test_api_*.py`、`tests/test_task_harness_service.py` | 测试 |
| Slide 4 | 五层 prompt 组合 | `src/ainrf/task_harness/prompting.py` | 源码 |
| Slide 4 | SSH 远程启动 Claude Code | `src/ainrf/task_harness/launcher.py` | 源码 |
| Slide 4 | SSE 流 + SQLite 持久化 | `src/ainrf/api/routes/tasks.py` | 源码 |
| Slide 5 | webui.sh 一键联调 | `scripts/webui.sh`、`tests/test_webui_sh.py` | 源码+测试 |
| Slide 5 | workspace browser | `src/ainrf/code_server.py`、`tests/test_code_server.py` | 源码+测试 |
| Slide 6 | skills package 设计 spec | `docs/LLM-Working/worklog/2026-04-23.md`（02:10） | worklog |
| Slide 6 | ARIS 探索实验 | `test/Mode1/experiments/`、`test/Mode1/idea-stage/` | 实验代码 |
| Slide 7 | 真实科研场景 pilot | `test/Mode1/idea-stage/PARTITION_FIRST_PLAN.md` | 设计文档 |

---

## 素材清单

- [ ] `assets/screenshot-tasks-page.png` — Tasks 页截图（需启动 webui.sh 后截取）
- [ ] `assets/screenshot-terminal-page.png` — Terminal 页截图
- [ ] `assets/screenshot-settings-page.png` — Settings 页截图
- [ ] `assets/control-plane.png` — 控制面链路图（由 `control-plane.mmd` 导出）
- [ ] `assets/task-harness-sequence.png` — Task Harness 时序图（由 `task-harness-sequence.mmd` 导出）

> 注：截图留空，由汇报人启动 `scripts/webui.sh` 后自行截取真实界面。
