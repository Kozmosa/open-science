---
aliases:
  - Legacy V1 Summary
  - 旧版 V1 / WebUI-v1 遗留总结
tags:
  - ainrf
  - legacy
  - cleanup
  - refactoring-plan
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
doc_nature: human-revised
last_human_reviewed: 2026-04-12
last_local_commit: workspace aggregate
---
# 旧版 V1 / WebUI-v1 遗留总结

> [!warning]
> 本文档用于在 cleanup-first realignment 过程中收拢旧版 P-series 与 W-series `LLM-Working` 文档。它保留后续仍可继承的接口、边界判断、验证经验与风险提示，同时明确标记哪些组件、行为和推进叙事已在本轮 cleanup 中被破坏性移除，不再作为当前项目承诺。

> [!abstract]
> 早期 `AINRF v1` 叙事曾围绕“bounded-autonomous orchestrator + WebUI-v1”推进，并在 `docs/LLM-Working/` 下形成 P1-P9、W1-W3 等分阶段计划、实现记录和 smoke 清单。随着项目转向单用户优先、task-centric、dashboard-first 的 realignment，这批文档不再适合作为分散入口继续维护。本总结将它们压缩为一份遗留继承说明，供后续需要追溯旧方案时统一查阅。

## 清理结论

- 旧版 P-series / W-series 文档已从 `docs/LLM-Working/` 主目录移除，不再作为当前执行计划入口。
- 旧版 orchestrator / WebUI-v1 相关思路只保留为历史背景，后续若需要借鉴，应从本总结提取“仍可继承的约束与经验”，而不是恢复原有阶段拆分。
- 当前项目的有效规划入口仍是 `[[LLM-Working/refactoring-plan/index]]` 及其 realignment 文档集。

## 仍应继承的内容

### 1. 可继承的工程边界

- 运行态文件继续放在 `.ainrf/` 下，而不是混入 `docs/` 或生成目录。
- 文档、CLI/服务代码、运行时状态存储应继续职责分离。
- task-scoped API 与本地 state/read model 的收口思路仍有参考价值：即便后续 contract 改写，也应保持状态写入点集中、避免平行持久化层分叉。
- 对外部依赖维持“离线自动化测试 + 真实 smoke checklist”两层验证方式，尤其适用于 SSH、第三方解析服务、远端运行时等能力。

### 2. 可继承的接口与交互经验

- task-scoped 资源形状比过早引入更多顶层资源更稳妥；审批、详情、事件等接口若继续存在，仍应优先保持围绕 task 聚合。
- 健康检查、鉴权失败、降级状态、fallback 路径应在 UI 或 API 中显式表达，避免把“能力未实现”伪装成“成功但无结果”。
- append-only 事件日志、历史回放、断点恢复、手工刷新 fallback 这些观察面设计原则仍然值得保留。
- secret 不应直接写入长期持久化状态；运行时 secret 与可审计状态需要分离。

### 3. 可继承的历史实现事实

- 旧方案曾落地并验证过以下方向，说明这些能力在仓库历史上不是纯空想，而是已经有过具体接口和验证经验：
  - 基于 `.ainrf/tasks/` / `.ainrf/artifacts/` / `.ainrf/events/` 的本地状态与事件布局。
  - FastAPI 服务骨架、API key 鉴权、任务详情/取消/工件查询等 task API 形状。
  - Human gate 的 waiting / resolved 生命周期、signed webhook、timeout reminder 等控制面语义。
  - task-scoped JSONL 事件日志与 SSE 历史回放/过滤/断点恢复。
  - 真实运行时 smoke 的失败分类思路，如 SSH 不可达、Claude 不可用、密钥缺失、project dir 不可写等。
- 上述事实可作为今后重建控制面或验证标准时的历史参考，但不等于当前实现方向必须按原模块边界复刻。

### 4. 可继承的产品判断

- “Project 只是 UI 组织层，不一定是后端一等资源”这一判断仍然有价值，应在 dashboard 设计里继续谨慎处理。
- mode、run、gate、artifact、timeline 之间需要清晰分层；不应让 UI 本地组织概念反向污染后端真相模型。
- mock 能力与真实能力必须显式区分，不能混成同一种成功路径。

## 在 cleanup 中被破坏性移除的内容

> [!danger]
> 以下内容已在本轮 cleanup 中视为退役对象。它们可以作为历史背景被描述，但不应再被当前文档、索引或实现计划当成有效承诺。

### 1. 被移除的推进叙事

- 按 P1-P9 连续推进“完整 orchestrator”的主线叙事。
- 按 W1-W5 推进 Gradio WebUI-v1 的独立工作台叙事。
- 把旧版 `v1-roadmap` / `webui-v1-roadmap` 当作当前 next release 的实施切片来源。

### 2. 被移除的组件与能力承诺

- Gradio `ainrf webui` 入口及其 WebUI-v1 页面、Project 本地工作台和 run 详情交互面。
- 以旧版 orchestrator 为中心的完整 TaskEngine / adapter / planner 主线承诺。
- 将 P-series 文档中的模块拆分、目录命名和阶段顺序继续视为现行工程边界。
- 任何把旧版 mock、占位路由或历史 API skeleton 直接包装成“当前产品能力”的说法。

### 3. 被移除的行为与默认假设

- 默认继续扩展 `.ainrf/webui/`、Gradio app shell 或 WebUI 本地 registry 的假设。
- 默认继续围绕“intake -> planning -> executing”的旧 runtime 叙事扩充文档的假设。
- 默认继续补齐 P8/P9 以完成早期双模式自治引擎闭环的假设。

## 从旧文档中保留下来的关键经验

### SSH / 真实运行时 smoke

- 对真实远端环境，必须区分“离线单测已通过”和“真实 smoke 已验证”两种结论。
- smoke 检查项应优先覆盖：联通性、依赖存在性、远端密钥/权限、工作目录可写性、失败分类可诊断性。

### 第三方解析与外部服务

- 外部 provider 契约要在接线前先被收敛成内部 contract，避免上层直接依赖第三方 JSON 字段。
- 对限流、超时、结构不足、provider 拒绝等失败模式，要么对象化，要么在接口层显式分类，不能把裸异常直接外漏为产品语义。

### 状态、事件与审批控制面

- 单 waiting gate 约束、append-only 摘要账本、事件回放与 reminder 去重，都是值得复用的控制面思路。
- 就算后续不沿用旧 artifact schema，也应保留“可追溯状态变化”和“审批/提醒行为可审计”的要求。

### UI / dashboard 边界

- 前端工作台适合消费真实 task/gate/event 契约，但不应反过来主导后端对象模型。
- 在真实数据不完整时，优先显示明确降级与空状态，而不是发明额外的持久化层来填补叙事。

## 后续使用建议

- 需要理解当前项目方向时，优先阅读 `[[framework/ai-native-research-framework]]` 与 `[[LLM-Working/refactoring-plan/index]]`。
- 需要追溯旧版 orchestrator / WebUI-v1 做过哪些判断时，阅读本文即可；只有在必须挖掘更细的历史实现细节时，才回看 git 历史，而不是恢复已删除的散档。
- 需要继承旧方案中的某一条经验时，应以“抽取原则或验证标准”的方式复用，而不是直接恢复原先的 phase 文档体系。

## 已压缩并移除的文档范围

### Historical implementation trail

- P1：旧版 V1 初始实施切片，确立 task/orchestrator 主线的首轮实现边界与分阶段推进框架。
- P2：补强早期控制面与任务流转接口，延续以 orchestrator 为中心的模块化拆分方向。
- P3：继续推进任务状态、事件或执行链路相关实现，使 V1 叙事从计划转向可运行骨架。
- P4：围绕服务化/CLI 接线补齐运行入口，扩展旧版 V1 作为统一 orchestrator 平台的承诺范围。
- P5：细化 task-centric API、状态存储或配套交互面，进一步固化旧版控制面的实现形状。
- P6：继续补足运行时、审批或可观测性相关能力，为后续自治闭环预留更多旧架构接点。
- P7：推进更完整的任务执行/自动化能力，使早期双模式研究引擎叙事继续向前延伸。
- P9：面向旧版自治 orchestrator 收尾的后续规划项，体现当时仍计划补齐完整闭环而非转向 cleanup realignment。
- W1：Gradio WebUI-v1 首轮工作台切片，建立旧版前端工作台与 Project/run 组织方式。
- W2：扩展 WebUI-v1 交互面与任务观察路径，继续把本地工作台包装为现行产品入口。
- W3：补充 WebUI-v1 后续工作台计划，延续旧版 run/detail/dashboard 式叙事。

- P-series：P1、P2、P3、P4、P5、P6、P7、P9 相关 implementation plan / impl / smoke checklist 文档。
- W-series：W1、W2、W3 相关 implementation plan 文档。

## 关联笔记

- [[framework/index]]
- [[framework/ai-native-research-framework]]
- [[framework/v1-roadmap]]
- [[framework/webui-v1-roadmap]]
- [[LLM-Working/refactoring-plan/index]]
- [[LLM-Working/worklog/2026-04-12]]
