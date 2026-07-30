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

发生冲突时，按以下顺序判断：

1. 当前代码、持久化 schema、generated transport 和正常测试定义已实现行为。
2. `PROJECT_BASIS.md` 定义跨会话长期工程约束。
3. `docs-site/docs/` 定义当前产品、用户、部署和公开架构 contract。
4. `docs/superpowers/specs/` 定义尚在决策或实施中的活跃设计。
5. `docs/reference/` 与 `docs/projects/` 提供当前工程参考和研究输入。
6. `docs/superpowers/specs/archived/`、`docs/archive/` 与 worklog 只用于追溯，不得覆盖当前 contract。

设计文档不能仅凭日期较新就覆盖代码或长期治理约束。若 accepted spec 尚未实现，必须明确写出“等待实现”；若代码已经偏离它，应重新确认、修订或归档。

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

满足任一条件时必须移入 `docs/superpowers/specs/archived/`：

- `implemented`：实现已完成，稳定结论已经提升到代码、测试、`PROJECT_BASIS.md`、`docs-site/docs/` 或 `docs/reference/`。
- `superseded`：被明确的后继设计取代。
- `retired`：方向被放弃。
- `conflicting`：核心前提与当前产品 contract 明显冲突，且不准备继续实施。

归档不等于删除或改写历史。历史 spec 中当时言之凿凿但后来被推翻的判断应原样保留；通过归档位置、状态说明和 `superseded_by` 指针表明它不再有效。

## 品牌转向示例

OpenScience 是当前产品品牌，`ainrf` 是稳定内部工程与运行时身份，`osci` 是前端设计系统和紧凑品牌命名空间。过去主张把 `ainrf` package、状态路径、Linux identity 或 telemetry 全量替换为 OpenScience/OSCI 的文档属于历史决策输入，不再定义当前方向。

处理这类转向时：

1. 在 `PROJECT_BASIS.md` 与当前架构文档写入新的长期规则。
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
