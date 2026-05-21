# research-dev skills package 设计

日期：2026-04-23

## 背景

我们准备在仓库内启动一套长期维护的 skills package，用于给一组预先约定的 research-project coding agents 提供统一、稳定、可复用的 research engineering 工作流指导。

这套 package 的目标不是服务当前 `scholar-agent` 仓库本身的局部约束，而是提供一套面向 research-project 脚手架的通用技能包，并通过标准化的 skill 结构兼容多个 coding agent。

已有约束如下：

- skills 包需要兼容 Claude Code、Codex 等多个 coding agent。
- 安装、卸载和发现逻辑不自定义实现，统一复用 `skills.sh` / `npx skills`。
- `skills/skills-index.md` 与 package 源码同目录维护，但它是维护者索引，不属于 installable skill surface。
- package 需要包含一个总入口 skill，以及按主题拆分的子 skill，以降低上下文占用和污染。
- package 内还需要包含一个用于初始化 research-project 脚手架的启动 skill。

## 目标

本次设计要达成以下目标：

1. 形成一个可被 `npx skills` 直接安装、卸载和发现的标准 skills package。
2. 采用单 package、多入口/多子 skill 的结构，保证入口薄、职责清晰、按需加载。
3. 提供一个 `project-init` skill，用于初始化“可直接开发”的 research-project runnable scaffold。
4. 为后续 skill 的持续扩展建立维护者索引、生命周期状态和准入规则。
5. 保持 package 对具体业务仓库低耦合，服务于一类研究工程脚手架，而不是单个现有仓库。

## 非目标

本次设计不做以下事情：

- 不把 `skills-index.md` 设计成 installable skill 或 agent 运行时依赖入口。
- 不为安装/注入再编写一套自定义脚本系统。
- 不让 `using-research-dev` 承担所有具体工程细则，避免它成为大而全的长技能。
- 不把 `project-init` 扩展成带 Web 服务、训练框架、任务编排等重业务模板。
- 不把 package 和当前 `scholar-agent` 仓库规则强绑定。

## 方案比较

### 方案 A：单 package，多入口，多子 skill（采用）

做法：

- 在同一个 package 内放置 `using-research-dev`、`project-init` 以及按主题拆分的运行期 skill。
- installable skill 都采用标准 `skills/<skill-name>/SKILL.md` 结构。
- `using-research-dev` 只负责路由，具体规范由子 skill 承担。
- `skills-index.md` 仅作为维护者索引存在。

优点：

- 结构接近 `superpowers`，容易理解和维护。
- 入口与细分 skill 可以解耦，降低上下文污染。
- 安装、发布和版本管理只需要围绕一个 package 进行。
- 便于后续增量加入新 skill，同时保持统一品牌和入口。

缺点：

- 需要提前定义清楚各 skill 的边界，避免交叉覆盖。

### 方案 B：单 package，少量大 skill

做法：

- 仍只有一个 package，但尽量把 research 开发流程内容聚合到少数几个大 skill 中。

优点：

- 首版写起来更快。

缺点：

- skill 一旦加载就带入大量无关规范，污染上下文。
- 后续拆分成本高。
- 总入口容易和执行细节耦合。

### 方案 C：拆成多个 package

做法：

- 将 research 开发流程、project 初始化等内容做成多个独立 package。

优点：

- 包级边界最干净。

缺点：

- 安装、发现、发布和维护成本更高。
- 与“单 package，统一入口”的目标不一致。

## 采用方案

采用方案 A：单 package，多入口，多子 skill。

设计原则是：

- 一个统一 package 承载整个 research-dev 能力集合。
- 入口 skill 保持薄，只做判断与路由。
- 具体规范拆分到主题 skill，按需加载。
- 面向维护者的索引、状态与路线图和面向 agent 的 installable skill 严格分离。

## Package 目录结构

`skills/` 是这套 package 源码与维护者文档共同所在的目录，但真正的 installable surface 仅由带 `SKILL.md` 的子目录构成。

推荐的初始结构：

```text
skills/
  skills-index.md
  using-research-dev/
    SKILL.md
  project-init/
    SKILL.md
  env-bootstrap/
    SKILL.md
  git-workflow/
    SKILL.md
  commit-style/
    SKILL.md
  repo-ops/
    SKILL.md
```

约束如下：

- `skills-index.md` 是维护者索引，不参与 `npx skills` 的 installable skill discovery。
- installable skill 必须是带 `SKILL.md` 的目录。
- 每个 skill 如需 supporting files，应放在各自目录下，避免根目录堆放共享杂项。
- 第一版不引入 `.curated/`、`.experimental/` 等层级；如后续需要成熟度分层，再按标准路径追加。

## Skill 职责边界

### `using-research-dev`

定位：package 总入口。

职责：

- 识别当前请求属于初始化、环境引导、git/worktree、提交规范还是仓库运维约束。
- 要求 agent 在合适时调用对应子 skill。
- 维护 package 的使用心智模型。

非职责：

- 不内联所有工程细则。
- 不替代子 skill 承担命令、目录、命名等具体规范。

### `project-init`

定位：research-project 脚手架初始化 skill。

职责：

- 将新仓库初始化为可直接开发的 runnable scaffold。
- 铺设 Python/uv 工具链、研究文档目录、agent guidance 和 git 约定。
- 定义 project scaffold 的初始合同和最小验证入口。

非职责：

- 不承载日常开发规范。
- 不扩展为业务应用模板或运行时平台模板。

### `env-bootstrap`

定位：开发环境与依赖引导 skill。

职责：

- 指导依赖缺失时如何排查与补齐。
- 明确 `uv`、lockfile、Python 版本与 `uv run` 的使用方式。
- 规定虚拟环境由 `uv` 管理，本地执行统一通过 `uv run`。

### `git-workflow`

定位：开发隔离与分支/worktree 规范 skill。

职责：

- 明确默认先开独立 worktree，再在对应分支上开发。
- 规定分支和 worktree 的命名约定。
- 指导何时开启新 worktree、何时允许继续当前工作区。

### `commit-style`

定位：提交规范 skill。

职责：

- 规定 Conventional Commits 首行风格。
- 规定正文重点应描述 why / what changed / impact。
- 给出何时提交、如何拆分提交的判断原则。

### `repo-ops`

定位：脚手架仓库日常工程约束 skill。

职责：

- 规定 worklog、specs、验证命令和目录边界。
- 规定哪些目录是长期知识、哪些目录是中间产物、哪些内容应版本化。
- 提醒 agent 在完成工作批次后同步补 worklog 与必要设计文档。

## 路由规则

`using-research-dev` 的设计目标是“短、准、只路由”。建议采用如下触发映射：

- 新建项目、接手空仓库、初始化 research 工程时，调用 `project-init`。
- 遇到依赖缺失、环境无法运行、不确定应该使用哪个 Python/venv 时，调用 `env-bootstrap`。
- 在开始实际开发、准备创建分支或判断是否需要 worktree 时，调用 `git-workflow`。
- 在需要补 worklog、写 specs、跑验证命令、判断目录边界时，调用 `repo-ops`。
- 在准备提交代码、统一提交信息或拆 commit 时，调用 `commit-style`。

这样可以保持以下边界：

- `using-research-dev` 不成为大 skill。
- `project-init` 只处理初始化，不承担日常运维规范。
- `repo-ops` 处理脚手架运行期约束，不回卷到初始化逻辑。

## `project-init` 产出的脚手架合同

`project-init` 的目标不是生成空目录，而是生成“可直接开发”的 research-project runnable scaffold。

“可直接开发”的最低合同定义为：初始化完成后，仓库至少具备稳定入口来执行以下命令：

- `uv sync`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check`

即使初始代码非常少，也必须保证这些命令有意义且路径稳定。

推荐脚手架结构：

```text
<repo>/
  pyproject.toml
  README.md
  .gitignore
  AGENTS.md
  PROJECT_BASIS.md
  docs/
    LLM-Working/
      worklog/
      specs/
  src/<project_slug>/
    __init__.py
  tests/
    test_smoke.py
  .worktrees/
```

### 脚手架默认约定

- Python 环境统一由 `uv` 管理。
- 本地执行入口统一使用 `uv run ...`。
- `.venv/` 作为本地产物存在，不纳入版本控制。
- `AGENTS.md` 用于项目级协作方式与 agent 操作约定。
- `PROJECT_BASIS.md` 用于长期工程约束。
- `docs/LLM-Working/worklog/` 用于按天追加工作日志。
- `docs/LLM-Working/specs/` 用于设计和方案文档。
- 默认开发隔离策略是先开 worktree，再在对应分支上工作。

### 默认 Git / Worktree 约定

- 分支命名：`feat/<slug>`、`fix/<slug>`、`docs/<slug>`、`chore/<slug>`。
- worktree 路径：`<repo>/.worktrees/<branch-slug>`。
- worktree 名与 branch slug 对齐，降低心智成本。

## 安装与发现契约

package 的安装、卸载和发现全部依赖 `skills.sh` / `npx skills`，不额外维护自定义注入脚本。

推荐约定：

- 本地迭代时支持从本地路径安装。
- 对外发布时支持从 GitHub repository 安装。
- 用户只需要关注 `npx skills add` / `remove` / `list` 等标准命令。

推荐示例：

```bash
npx skills add <repo-or-local-path>
npx skills add <repo-or-local-path> --skill using-research-dev
npx skills add <repo-or-local-path> --skill project-init
npx skills remove using-research-dev
npx skills list
```

技能发现规则由标准 `SKILL.md` 目录结构保证；`skills-index.md` 不参与运行时发现。

## `skills-index.md` 的维护范围

`skills-index.md` 的受众是 package 维护者，而不是运行时 agent。

它应该维护以下内容：

- 当前 stable skills 清单。
- 每个 skill 的一句话定位。
- 入口关系，例如 `using-research-dev` 会路由到哪些子 skill。
- 当前 package 的推荐安装方式。
- 每个 skill 的状态：`draft` / `tested` / `stable`。
- 待补充的 skill 候选和扩展路线。

它不应该承担以下职责：

- 不作为 agent 的必读运行时文档。
- 不取代各 skill 自身的 `SKILL.md`。
- 不写入仅对单个仓库有效的临时实现细节。

## Skill 生命周期与准入规则

为了让 package 保持稳定，需要为新 skill 进入 stable 集合定义明确准入规则。

推荐生命周期：

- `draft`：仅完成草案，尚未完成基线测试。
- `tested`：已完成 baseline / with-skill 测试，但仍待纳入稳定集合。
- `stable`：通过准入流程，可写入 `skills-index.md` 作为稳定 skill。

推荐准入流程：

1. 使用 `skill-creator` 起草新 skill。
2. 按 TDD 先设计 baseline pressure scenarios。
3. 在没有该 skill 的情况下运行 baseline，记录失败模式与 rationalizations。
4. 根据 baseline 结果编写 `SKILL.md`。
5. 在有该 skill 的情况下重新运行验证场景。
6. 根据新发现的 loopholes 做 refactor，直到场景通过。
7. 通过后才允许把 skill 从 `draft` 提升为 `stable`，并写入 `skills-index.md`。

这条规则的核心目的不是形式化，而是保证 stable package 中的 skill 真正具有可复用性和抗 rationalization 能力。

## 演进策略

第一批 stable skill 集合建议仅包含：

- `using-research-dev`
- `project-init`
- `env-bootstrap`
- `git-workflow`
- `commit-style`
- `repo-ops`

后续如要增加更多 skill，应遵守两条规则：

- 新 skill 要么服务一个独立判断点，要么服务一个清晰的工程面，不与既有 skill 争夺同一职责。
- 若某 skill 的内容开始显著膨胀，应优先考虑再次拆分，而不是继续扩写总入口。

## 验证与后续工作

本 design 完成后，下一阶段应分两步推进：

1. 先为 package 建立目录骨架与维护者索引，并确定 `project-init` 生成的实际模板文件。
2. 再按 `skill-creator + TDD` 流程逐个实现第一批 stable skill，而不是一次性批量写完全部 skill。

这样可以保证 package 先有稳定结构，再逐步填充经过验证的 skill 内容。
