# OpenScience Project Basis

> 用途：记录本仓库长期有效、跨会话应持续遵守的工程约束。临时方案、一次性实验和未落地设计不直接写入本文件。

## 项目目标与当前边界

- 项目名称：`OpenScience`
- **OpenScience** 是用户可见的产品与品牌名称，以及前端使用的标识（缩写可以使用osci）；`AINRF` / `ainrf` 是稳定的内部工程与后端使用的标识。Python package/import namespace、状态路径、Linux identity、部署资源和 telemetry namespace 等和后端相关部分默认使用 `ainrf`。
- 面向用户的 WebUI、产品文档、CLI help 和项目宣传材料的品牌标识等用 OpenScience。
- 后端配置规范使用 `AINRF_*`；对应的 `OPENSCIENCE_*` 后端变量仅作为兼容别名。前端配置以及仓库级开发、CI 和编排配置使用 `OPENSCIENCE_*`。
- `docs/`、`ref-repos/` 与其他研究笔记材料的主要职责是为 OpenScience 的产品设计、实现取舍和历史追溯提供参考输入，不是工程实现的权威文档。
- `vsa` 在本项目中指工作在容器内的 vibe scientist agent 研究员预设。

## 约束优先级

- 本文件是最高优先级、经过人工审阅的长期项目事实与规则来源，只允许由用户人工修改；任何 Agent 都不得修改本文件。
- `AGENTS.md`、`CLAUDE.md`、局部 Agent 指令及其他文档不得与本文件冲突。发现冲突时，Agent 必须停止受影响的判断并显式询问用户，不得自行选择或修正文档。
- 当本文件与代码、schema、测试、部署配置或其他可靠工程事实出现漂移时，Agent 必须请用户重新审阅工程事实，由用户决定修正工程实现还是人工修订本文件。

## LLM 协作与文档目录约定

- `docs-site/docs/` 是当前对外的公开产品文档的长期目录。
- `docs/` 是工程内部的文档目录，保存活跃设计、工程参考、研究输入、历史决策和工作日志；它不是当前产品 contract 的唯一 authority。
- `docs/documentation-governance.md` 定义文档优先级、生命周期、活跃 spec 与归档规则等文档治理策略；新增或移动长期文档必须遵守该文件。
- `docs/framework/` 用于框架设计、RFC、路线图和体系化方法论。
- `docs/projects/` 用于外部项目调研与对照分析。
- `docs/summary/` 用于跨项目综述、矩阵和汇总结论。
- 文档文件名使用英文 slug，正文以中文为主，优先使用 Obsidian 双链格式，例如 `[[framework/v1-rfc]]`。
- 会话日志、实现复盘或 agent 中间产物，存放于`docs/LLM-Working/` 当中。
- 每日工作日志固定存放于 `docs/LLM-Working/worklog/`，按天创建 `YYYY-MM-DD.md` 文件，并在同一日内持续追加。
- 工作日志默认按“每个已完成的修改计划 / 工作批次追加一条 changelog”记账，不把同一批次里的 edit、validation、commit 强拆成多条流水账。
- 每条 changelog 至少包含时间、批次或计划名、实际改动摘要与验证结论；若该批次产生 commit，在同一条末尾补充 commit hash 与 commit 首行。
- changelog 应总结“这一批完成了什么、影响了哪些部分、验证结果如何”，不要简单复述 commit message 或原子提交标题。
- 示例：`2026-03-16 10:40 changelog：完成 P3 worklog 规则调整，统一仓库级约束并同步修订 P3 规划说明；执行 docs build 成功；关联提交：abcd123 docs: revise worklog policy`

## 工程编码风格与规范

### 语言与工具

- 主要语言：`Python 3.13` 与 `Markdown`
- 运行时与构建：`uv run` 驱动的 Python CLI 与脚本执行，文档侧由 `docs-site/` 中的 VitePress 构建
- 包管理：`uv`（后端）、`npm`（docs-site）
- 主要框架或库：`Typer`、`structlog`、`PyYAML`、`FastAPI`、`VitePress`、`pytest`、`ruff`

### 编译器 / 类型系统约束

- Python 版本要求固定为 `>=3.13`。
- `src/ainrf/`、`tests/` 和 `scripts/` 中的 Python 代码必须包含严格类型标注；缺失类型标注视为缺陷。
- 静态类型检查以 `ty check` 为准，提交前必须通过。
- 代码风格和基础质量由 `ruff check`、`ruff format` 和 `pytest` 共同约束。
- 当前项目不以口头约定替代落地配置；能进入长期约束的检查项，应当有对应命令或配置文件支撑。

### 代码风格

- Python 模块使用标准 import 模块体系与 `snake_case` 命名；类名使用 `PascalCase`。
- 统一使用 4 空格缩进，字符串风格与格式化结果以 `ruff format` 为准。
- 优先保持实现简洁，避免为尚未验证的运行时能力过早抽象。
- 修改既有文件时优先遵循文件原有风格，再考虑局部重构。
- 非必要不添加注释；只有在复杂、非显而易见逻辑处补充简洁说明。
- 笔记类文档要求 YAML frontmatter、Obsidian wikilink 和可被站点构建脚本稳定处理的 Markdown 结构。

### 错误处理与边界

- 对不可能状态与关键解析失败应快速失败，不静默吞错。
- 对外部输入、文件路径、frontmatter、wikilink 解析结果等边界值，在入口处完成校验与收敛。
- CLI 或脚本层输出应提供可定位问题的错误信息，避免只给出模糊失败描述。
- 生成目录 `site/`、`.cache/html-notes/` 与 `docs-site/dist/` 视为构建产物，不直接手工编辑。

## 架构解耦要求

- 文档构建逻辑、CLI 入口、日志配置和未来研究运行时能力应继续保持职责分离。
- `src/ainrf/` 负责可安装 Python 包与 CLI/服务运行时代码，避免把仓库级脚本逻辑直接堆入命令入口。
- `frontend/` 负责 OpenScience 的 WebUI 前端；它与 `src/ainrf/` 一起构成仓库的核心产品实现面。
- `scripts/` 负责本地构建与辅助流程；若脚本演化为可复用运行时能力，应回收进入 `src/ainrf/`。
- `docs/` 负责内部长期知识资产；不要把仅用于一次调试的中间日志混入知识库主目录。
- `docs/projects/`、`docs/summary/`、`ref-repos/` 与其他调研材料默认视为参考语料层，不直接定义 OpenScience 当前产品 contract。
- 未来扩展 `ainrf` 时，优先把核心研究逻辑设计为可脱离具体宿主 CLI 复用的模块，再在 Typer 命令层做装配。
- Backend 以 committed-v2 state 为唯一 product authority；其中 Task 产品行为以 Conversation Domain 的 Task、Turn、Item、TurnSubmission、RuntimeExecution 与 EngineConversationBinding 为正式 authority。普通产品路径不得读写旧 Attempt/RuntimeSession；旧表仅可由 standalone migration、显式 legacy-authority compatibility Adapter 或管理取证使用，不得重新引入 legacy read fallback、长期 dual-write、双读或双写。产品 import graph 必须保持无 cycle，且 non-API Module 不得通过直接 import、惰性 import、动态 import 或字符串入口反向依赖 `ainrf.api`。FastAPI application construction、HTTP process composition 与 server lifecycle 属于 HTTP Adapter。
- Canonical OpenScience product HTTP prefix 是 `/api`。历史 root 与 product `/v1` aliases 已在完成 caller audit、自动验证、隔离环境手动验收并经用户明确批准后删除；不为收集 compatibility telemetry 而将未经完整手动验收的代码部署到 production。`/v1/models` 与 `/v1/messages` 是独立、长期支持的外部模型协议 Interface，不是 OpenScience product route aliases。后续 compatibility removal 必须继续基于明确 caller inventory、充分验证证据和用户逐批批准；证据不足时 fail closed。
- FastAPI/Pydantic OpenAPI 是唯一 transport schema authority。Frontend generated transport 必须可确定性重建并通过 drift gate；UI 通过 feature adapter 消费 view model，不直接消费 raw generated payload。
- Frontend 依赖方向为 `app -> features -> shared/design-system`；`shared`、`design-system` 和 legacy component 层不得反向依赖 feature。
- 当前架构、release/rollback contract 与 compatibility inventory 的长期产品文档位于 `docs-site/docs/architecture.md`。

## 目录约定

- `docs/`：研究知识库与历史设计材料（Obsidian 笔记）。
- `docs-site/`：OpenScience 产品文档站点（VitePress，部署至 GitHub Pages）。
- `frontend/`：OpenScience WebUI 前端。
- `src/ainrf/`：OpenScience 稳定的 Python package/import namespace、CLI 入口、后端 API、日志与运行时代码。
- `src/ainrf/agentic_researcher/`：保留研究员 preset、engine 配置及显式 compatibility 所需的数据类型；它不拥有 Task CRUD、Conversation persistence 或 Task lifecycle 写入。
- `src/ainrf/domain/`：当前 committed-v2 Project、Workspace、Environment、Context 与 Conversation application Modules。正式 Conversation Interface 负责 Task/Turn/Item/Submission/Execution/Binding 的状态转换、幂等、授权、因果 guard 与事务；worker 通过私有 execution Interface 使用同一深 Module，HTTP、runtime driver 和 persistence implementation 位于各自 Seam 的 Adapter。该 Depth 为 caller 提供 Leverage，并将状态机和可靠性规则保持在单一 Locality。`pause` 不属于正式 Conversation Interface；停止 active execution 使用 interrupt，Retry 创建带 `retry_of_turn_id` 的新 Turn。
- `src/ainrf/harness_engine/`：OpenScience 执行引擎抽象，封装 claude-code、agent-sdk、codex-app-server
- `tests/`：CLI smoke tests 与后续 Python 测试。
- `scripts/`：本地构建与预览辅助脚本。
- `ref-repos/`：参考仓库，只读研究输入，不在此目录内直接做业务开发，也不把它们视为本仓库主产品源码的一部分。

## 技术栈与官方参考链接

- Python
  - reference: `https://docs.python.org/3/`
- uv
  - reference: `https://docs.astral.sh/uv/`
- Typer
  - reference: `https://typer.tiangolo.com/`
- VitePress
  - reference: `https://vitepress.dev/`
- Ruff
  - reference: `https://docs.astral.sh/ruff/`
- pytest
  - reference: `https://docs.pytest.org/`

## 开发与验证命令

- 安装依赖：`UV_CACHE_DIR=/tmp/uv-cache uv sync --dev`
- 本地开发：`UV_CACHE_DIR=/tmp/uv-cache uv run openscience --help`
- 生产构建：`cd docs-site && npm run build`
- 快速开发反馈：`bash scripts/ci.sh l0`
- 完整确定性门禁：`bash scripts/ci.sh l1`
- 后端全量测试：`bash scripts/test.sh all`（默认最多 8 个 worker，并将 race/contention 测试串行运行）
- 预览：`cd docs-site && npm run dev`
- 其他关键命令：
  - `npm --prefix frontend run check:transport`
  - `npm --prefix frontend run lint`
  - `npm --prefix frontend run test:run`
  - `npm --prefix frontend run build`
  - `npm --prefix docs-site run build`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests scripts`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests scripts`

## 本地调试与环境约定

- 本地标准入口优先使用 `uv run`，避免手工维护与锁文件不一致的虚拟环境。
- 本仓库不在标准文档中记录开发机私有绝对路径、账号信息或密钥路径。
- 本地辅助脚本纳入版本控制；产品文档使用 `docs-site/` 下的 VitePress 构建。
- 日志输出当前以标准输出为主；CLI 运行时日志统一经 `structlog` 配置，后续服务化时应继续沿用统一日志入口。
- 排障优先级：
  - 先检查 `uv` 环境、依赖安装与 Python 版本是否满足 `>=3.13`
  - 再检查文档源文件 frontmatter、wikilink 与构建脚本输入是否一致
  - 最后检查 CLI 行为、日志配置和测试覆盖是否与当前 scaffold 状态匹配

## 部署与运维模型

- OpenScience 是开源项目，主要部署场景是实验室内部环境，不以互联网企业级公共服务为默认运行模型。
- 运维人员可以安排维护窗口；生产升级、数据迁移和故障恢复允许最多约 2–3 小时的计划内停机。
- 项目不要求互联网服务级别的持续可用性、零停机发布或任意中断后的全自动恢复。
- 项目不以合规审计、高保证供应链证明或逐步骤发布证据留存为默认要求。
- 生产发布应优先采用简单、可理解、可人工恢复的维护窗口流程，避免为未确认的连续可用性或审计需求引入复杂的发布控制面。
- 必须保留的生产底线包括：发布前完整备份及恢复验证、前后端与 worker 版本一致、必要的数据迁移、凭据不进入镜像或浏览器制品、发布后 smoke test，以及失败时可执行的人工 rollback。
- 不可变制品、release manifest 和 L4 验收应以满足上述部署模型的最小实现为目标；除非部署需求发生变化，不建设零停机切换、复杂发布 ledger、逐文件供应链绑定或任意阶段中断后的自动接管恢复。

## Git 提交信息约定

- commit 首行使用 Conventional Commits，使用英文简要描述主要变更。
- 建议格式：`feat: ...` / `fix: ...` / `refactor: ...` / `docs: ...` / `chore: ...`。
- commit message 正文使用团队统一语言，说明本次修改细节、影响范围与必要背景。
- 正文使用 Markdown 无序列表分点描述，优先说明“为什么改”和“改了什么”。
- 需要换行时，使用多个 `-m` 参数或等效方式提交，不在字符串中写字面量 `\n`。
- 默认保持“一次 commit 对应一个逻辑工作批次”，避免把无关的前端、后端、文档和仓库卫生改动混在同一提交中。
- `docs/LLM-Working/worklog/` 下的当日 worklog 更新不要求单独使用 `docs:` 或 `chore:` 提交；它默认应与对应的功能、修复、重构等工作批次一起提交。
- `AGENTS.md`、`CLAUDE.md`、`PROJECT_BASIS.md` 等仓库根级长期约束文件发生修改时，应使用单独的 `docs:` 或 `chore:` 提交进行记录；同一个提交可以同时包含多个此类根级约束文件的更新。

## Git 分支与工作区约定

- `master` 是受保护的稳定主线；默认只接受 PR 合入，仅在仓库清理、历史整理或经明确授权的场景下允许强推。
- `develop` 是预发布缓冲区，用于联调、批量验证和发布前整合；它不是默认的新开发起点。
- 新开发默认从最新 `master` 起分支，而不是从 `develop` 起分支。
- 推荐的正式分支前缀为：`feat/`、`fix/`、`refactor/`、`docs/`、`chore/`。
- `develop` 默认接受来自 `master` 的同步；只有在整合与验证完成后，才从 `develop` 回流到 `master`。
- `develop` 允许直接 merge 作为缓冲区使用，但进入 `master` 仍应走 PR。

## Git 卫生与 Worktree 约定

- 默认采用 worktree-first 开发范式：非微小改动优先在独立 worktree 中实施。
- 主工作区应尽量保持干净，主要用于同步、检查、轻量文档修改与受控清理动作，而不是默认功能开发现场。
- 正式开发与 Agent 工作区统一放在 `.claude/worktrees/<branch>`。
- 合并完成或确认放弃后，应删除对应本地分支和 worktree。
- 远程不应长期保留 `worktree-*`、`agent/*` 或其他明显过程性命名分支。
- 进行仓库卫生巡检时，应使用 `git fetch --prune origin` 清理 stale remote-tracking refs，避免把本地过期引用误判为真实远程状态。
- 严禁提交 `.env`、本地 API key、调查导出物和其他本地敏感或一次性产物。

## 变更维护原则

- 修改长期工程约定时，优先更新本文件。
- 新增长期有效的知识结构、构建规则或运行时约束时，应同步更新相关 `docs-site/docs/` 或 `docs/` 文档，并在必要时从本文件补充索引。
- 新增 CLI 表面、解析行为或构建脚本契约时，必须同步补充或更新 `tests/` 中的 smoke tests。
- `LLM-Working`目录也需要纳入版本管理
- 对仓库进行实际修改、开发、验证或提交时，应同步追加当日 `docs/LLM-Working/worklog/YYYY-MM-DD.md`，不得把工作记录只留在会话上下文中。
