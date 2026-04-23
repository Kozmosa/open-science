# Scholar Agent Project Basis

> 用途：记录本仓库长期有效、跨会话应持续遵守的工程约束。临时方案、一次性实验和未落地设计不直接写入本文件。

## 项目目标与当前边界

- 项目名称：`scholar-agent`
- 当前主要目标：把 `ainrf` 持续收敛为本仓库的核心前后端产品，包括可安装 CLI、后端 API、WebUI 控制面，以及与 environment / terminal / task / workspace browser 相关的运行时能力。
- `docs/`、`ref-repos/` 与其他研究笔记材料的主要职责是为 `ainrf` 的产品设计、实现取舍和历史追溯提供参考输入，而不是继续充当仓库的默认产品中心。
- `vsa` 在本项目中指工作在容器内的 vibe scientist agent 研究员预设。

## 约束优先级

- 更高优先级的局部约束文件，尤其是仓库根目录的 `AGENTS.md`，在用户当次指令和目录内更近的局部约束上优先级更高。
- 本文件声明的长期工程约定必须遵守，当本文档与工程出现冲突，显式提示用户处理。

## LLM 协作与文档目录约定

- 本仓库现有长期文档主目录是 `docs/`；新增需要长期维护、会被纳入知识库与站点构建的 Markdown 内容，默认放入 `docs/` 下合适子目录。
- `docs/` 的默认入口与主叙事应服务于当前 `ainrf` 产品面；研究笔记、外部项目调研与历史设计文档继续保留，但不应再与 AINRF 当前实现面竞争同等入口地位。
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
- 运行时与构建：`uv run` 驱动的 Python CLI 与脚本执行，文档侧由 `scripts/build_html_notes.py` 构建 MkDocs 站点
- 包管理：`uv`
- 主要框架或库：`Typer`、`structlog`、`PyYAML`、`MkDocs`、`mkdocs-material`、`mkdocs-mermaid2-plugin`、`pytest`、`ruff`

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
- 生成目录 `site/` 与 `.cache/html-notes/` 视为构建产物，不直接手工编辑。

## 架构解耦要求

- 文档构建逻辑、CLI 入口、日志配置和未来研究运行时能力应继续保持职责分离。
- `src/ainrf/` 负责可安装 Python 包与 CLI/服务运行时代码，避免把仓库级脚本逻辑直接堆入命令入口。
- `frontend/` 负责 AINRF 的 WebUI 前端；它与 `src/ainrf/` 一起构成仓库的核心产品实现面。
- `scripts/` 负责本地构建与辅助流程；若脚本演化为可复用运行时能力，应回收进入 `src/ainrf/`。
- `docs/` 负责长期知识资产与产品文档；不要把仅用于一次调试的中间日志混入知识库主目录。
- `docs/projects/`、`docs/summary/`、`ref-repos/` 与其他调研材料默认视为参考语料层，不直接定义 AINRF 当前产品 contract。
- 未来扩展 `ainrf` 时，优先把核心研究逻辑设计为可脱离具体宿主 CLI 复用的模块，再在 Typer 命令层做装配。

## 目录约定

- `docs/`：AINRF 产品文档、研究知识库与历史设计材料。
- `frontend/`：AINRF WebUI 前端。
- `src/ainrf/`：AINRF Python 包、CLI 入口、后端 API、日志与运行时代码。
- `tests/`：CLI smoke tests 与后续 Python 测试。
- `scripts/`：本地构建与预览辅助脚本。
- `site/`、`.cache/html-notes/`：生成产物，仅由构建流程维护。
- `ref-repos/`：参考仓库，只读研究输入，不在此目录内直接做业务开发，也不把它们视为本仓库主产品源码的一部分。

## 技术栈与官方参考链接

- Python
  - reference: `https://docs.python.org/3/`
- uv
  - reference: `https://docs.astral.sh/uv/`
- Typer
  - reference: `https://typer.tiangolo.com/`
- MkDocs
  - reference: `https://www.mkdocs.org/`
- MkDocs Material
  - reference: `https://squidfunk.github.io/mkdocs-material/`
- Ruff
  - reference: `https://docs.astral.sh/ruff/`
- pytest
  - reference: `https://docs.pytest.org/`

## 开发与验证命令

- 安装依赖：`UV_CACHE_DIR=/tmp/uv-cache uv sync --dev`
- 本地开发：`UV_CACHE_DIR=/tmp/uv-cache uv run ainrf --help`
- 生产构建：`UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/build_html_notes.py build`
- 测试：`UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/`
- 预览：`UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/build_html_notes.py serve`
- 其他关键命令：
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ty check`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests`

## 本地调试与环境约定

- 本地标准入口优先使用 `uv run`，避免手工维护与锁文件不一致的虚拟环境。
- 本仓库不在标准文档中记录开发机私有绝对路径、账号信息或密钥路径。
- 本地辅助脚本如 `scripts/build.sh`、`scripts/serve.sh` 纳入版本控制。
- 日志输出当前以标准输出为主；CLI 运行时日志统一经 `structlog` 配置，后续服务化时应继续沿用统一日志入口。
- 排障优先级：
  - 先检查 `uv` 环境、依赖安装与 Python 版本是否满足 `>=3.13`
  - 再检查文档源文件 frontmatter、wikilink 与构建脚本输入是否一致
  - 最后检查 CLI 行为、日志配置和测试覆盖是否与当前 scaffold 状态匹配

## Git 提交信息约定

- commit 首行使用 Conventional Commits，使用英文简要描述主要变更。
- 建议格式：`feat: ...` / `fix: ...` / `refactor: ...` / `docs: ...` / `chore: ...`。
- commit message 正文使用团队统一语言，说明本次修改细节、影响范围与必要背景。
- 正文使用 Markdown 无序列表分点描述，优先说明“为什么改”和“改了什么”。
- 需要换行时，使用多个 `-m` 参数或等效方式提交，不在字符串中写字面量 `\n`。

## 变更维护原则

- 修改长期工程约定时，优先更新本文件。
- 新增长期有效的知识结构、构建规则或运行时约束时，应同步更新相关 `docs/` 文档，并在必要时从本文件补充索引。
- 新增 CLI 表面、解析行为或构建脚本契约时，必须同步补充或更新 `tests/` 中的 smoke tests。
- `LLM-Working`目录也需要纳入版本管理
- 对仓库进行实际修改、开发、验证或提交时，应同步追加当日 `docs/LLM-Working/worklog/YYYY-MM-DD.md`，不得把工作记录只留在会话上下文中。
