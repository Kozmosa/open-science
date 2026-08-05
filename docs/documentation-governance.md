---
aliases:
  - OpenScience 文档治理
tags:
  - openscience
  - documentation
  - governance
doc_state: current
---
# 文档 authority 与生命周期

本文定义 OpenScience 仓库的长期文档分层、authority 顺序和归档规则。它负责回答“当前事实在哪里”“设计何时仍然活跃”“频繁转向后如何保留历史但避免污染当前上下文”。

## Authority 顺序

不同文档和工程证据各自负责不同层面的事实：

1. `PROJECT_BASIS.md` 是最高优先级、经过人工审阅的长期项目事实与规则来源。
2. 当前代码、持久化 schema、generated transport 和正常测试定义当前已实现行为。
3. `docs-site/docs/` 定义当前产品、用户、部署和公开架构 contract。
4. `docs/superpowers/specs/` 定义尚在决策或实施中的活跃设计。
5. `docs/reference/` 与 `docs/projects/` 提供当前工程参考和研究输入。
6. `docs/superpowers/specs/archived/`、`docs/archive/` 与 worklog 只用于追溯，不得覆盖当前 contract。

`PROJECT_BASIS.md` 与当前工程事实并不是可以由 Agent 自动择一采信的普通优先级关系。如果代码、schema、测试、部署配置或其他可靠工程证据与 `PROJECT_BASIS.md` 冲突，Agent 必须停止受影响的判断，向用户报告 drift，并请用户决定修正工程实现还是人工修订 `PROJECT_BASIS.md`。Agent 永远不得修改 `PROJECT_BASIS.md`。

设计文档不能仅凭日期较新就覆盖代码或长期治理约束。若 accepted spec 尚未实现，必须明确写出“等待实现”；若代码已经偏离它，应重新确认、修订或归档。

## Agent instruction planes

仓库明确区分 contributor agent 与产品运行时 research agent 的提示平面，避免两个同名 `CLAUDE.md` 被误认为同一 authority：

| 平面 | 入口与来源 | 职责 | 维护规则 |
| --- | --- | --- | --- |
| Durable project basis | `PROJECT_BASIS.md` | 项目身份、长期边界、架构 invariant、维护与安全底线 | 只允许用户人工修改；其他提示不得覆盖 |
| Contributor agent | `AGENTS.md`、任务相关 `.rules/` 与本文件定义的 current docs | 代码贡献、验证、worktree、文档与运维协作方式 | `AGENTS.md` 是跨 Agent 宿主的 canonical 操作入口；细节按任务渐进披露 |
| Claude host adapter | 根目录 `CLAUDE.md` | 让 Claude Code 显式导入 `PROJECT_BASIS.md` 与 `AGENTS.md` | 必须保持纯 import stub，不独立复制或新增规则 |
| Runtime operator guardrail | `deploy/config/CLAUDE.md`，经容器 entrypoint 与 Agent SDK config 复制链注入 | PDF 分块、工具输出上限、SDK transport 与错误恢复等产品运行时行为 | 只约束 OpenScience 启动的 research-agent 会话；不得覆盖 contributor authority |

机器或开发者私有提示只可记录非规范性的本机事实，例如可执行文件位置或资源上限。它们不得覆盖项目身份、架构、权限、production safety、文档 authority 或其他 `PROJECT_BASIS.md` 长期规则，也不得成为团队依赖但不可审阅的隐藏 contract。

### 加载与渐进披露

1. Claude Code 通过根 `CLAUDE.md` 的 import stub 加载两个 canonical 根文件；支持 `AGENTS.md` 的宿主直接发现同一操作入口。
2. `AGENTS.md` 只保留跨任务必需的 authority、工作原则、上下文路由、安全与验证入口。
3. `.rules/`、subsystem README 和 current architecture docs 只在任务命中其路由时加载，不递归读取无关 reference、archive 或历史 spec。
4. README 默认是导航层，不因目录更近或日期更新而获得更高 authority；它必须指向当前 contract，并接受 drift gate 检查。
5. 已归档 spec、worklog 与研究材料只能解释历史，不能反向注入当前实现要求。

### Instruction drift gate

`uv run python scripts/check_agent_instructions.py` 检查 Claude import stub、canonical 文件存在性、根指令必要章节、受治理文档的本地 Markdown 链接、已知退休路径和 runtime guardrail 注入链。该检查进入 L0 与 L1 backend gate，用于捕获结构性漂移；语义冲突仍必须由 Agent 报告并由用户裁定，不能假装由字符串检查自动解决。

## 目录职责

| 目录 | 职责 | 是否定义当前事实 |
| --- | --- | --- |
| `docs-site/docs/` | 产品、用户、部署、运维、公开架构 | 是 |
| `docs/superpowers/specs/` | 活跃的 proposed/accepted/in-progress 设计 | 只定义目标方向 |
| `docs/superpowers/specs/archived/` | implemented/superseded/retired 设计记录 | 否 |
| `docs/reference/` | 当前事实性工程参考 | 是，限其明确主题 |
| `docs/projects/` | 仍活跃的外部项目研究 | 否，作为设计输入 |
| `docs/proposals/` | 等待确认的提案 | 否 |
| `docs/archive/` | 历史方向、完成提案和历史 working notes | 否 |
| `docs/LLM-Working/worklog/` | append-only 实施审计记录 | 否 |
| `docs/superpowers/plans/` | 未提交的临时 implementation plan | 否，且不得提交 |

## Spec 生命周期

活跃 spec 只允许使用以下状态：

- `proposed`：仍待确认，不能作为已批准 requirement。
- `accepted`：方向已确认但可能尚未实现。
- `in-progress`：正在实施，必须能对应当前工作切片。

每份活跃 spec 必须在 YAML frontmatter 中声明 `status`、`last_reviewed` 和 `review_by`。复审周期最长为 30 天；超过 `review_by` 且尚未实施的 spec，在重新审阅前不得作为可信实施依据。若它已经过时且不具备长期迁移或决策追溯价值，可以直接删除。

满足任一条件时必须移入 `docs/superpowers/specs/archived/`：

- `implemented`：实现已完成，稳定结论已经提升到代码、测试、`PROJECT_BASIS.md`、`docs-site/docs/` 或 `docs/reference/`。
- `superseded`：被明确的后继设计取代。
- `retired`：方向被放弃。
- `conflicting`：核心前提与当前产品 contract 明显冲突，且不准备继续实施。

归档不等于删除或改写历史。历史 spec 中当时言之凿凿但后来被推翻的判断应原样保留；通过归档位置、状态说明和 `superseded_by` 指针表明它不再有效。

## 品牌转向示例

OpenScience 是当前产品品牌，`ainrf` 是稳定内部工程与运行时身份，`osci` 是前端设计系统和紧凑品牌命名空间。过去主张把 `ainrf` package、状态路径、Linux identity 或 telemetry 全量替换为 OpenScience/OSCI 的文档属于历史决策输入，不再定义当前方向。

处理这类转向时：

1. 请用户人工复核并在 `PROJECT_BASIS.md` 写入新的长期规则，同时更新当前架构文档。
2. 把冲突 spec 移入 archive，而不是悄悄重写其历史论证。
3. 在仍活跃的后继 spec 中明确新的范围与 supersedes 关系。
4. 对可自动验证的范围增加 lint、测试或文档 drift gate。

## Proposal、working note 与 plan

- `docs/proposals/` 只保留等待确认的提案。接受后形成 active spec；实施完成、拒绝或失去相关性后移入 `docs/archive/proposals/`。
- `docs/LLM-Working/` 根目录不长期堆放已完成调查或 proposal；有追溯价值的完成材料移入 `docs/archive/working-notes/`，工作日志继续保留在 `worklog/`。
- `docs/superpowers/plans/` 中的 implementation plan 不提交。计划完成后删除，不通过 zip、备份文件或仓库内归档包保存。

## 维护检查

每轮重大转向或完成一个大型实施阶段后，应检查：

1. 活跃 spec 是否仍然 proposed、accepted 或 in-progress。
2. 已实现结论是否已经提升到长期 authority。
3. superseded/retired/conflicting 文档是否已经归档。
4. active spec、索引和相对链接是否仍然有效。
5. `docs/superpowers/plans/` 是否没有 tracked 文件。
6. 用户品牌文案和内部工程身份是否仍符合 `PROJECT_BASIS.md`。
