# Active design specifications

本目录只保存仍在决策或实施中的 OpenScience 设计。`PROJECT_BASIS.md` 是最高优先级、经过人工审阅的长期项目事实与规则来源；代码和测试记录当前已实现行为，`docs-site/docs/` 记录当前产品 contract。三者发生漂移时必须请用户裁定，不得由 Agent 自动择一覆盖。生命周期规则见 [`../../documentation-governance.md`](../../documentation-governance.md)。

所有 active spec 必须在 YAML frontmatter 中声明 `status`、`last_reviewed` 和 `review_by`，且复审周期不得超过 30 天。

## Active inventory

| Spec | 状态 | 说明 |
| --- | --- | --- |
| `2026-07-11-five-layer-hybrid-ci-design.md` | accepted / partially implemented | L0/L1 已落地；L2/L3 保持有界验证，L4 采用允许停机的简单维护窗口发布，独立 release staging 可选 |
| `2026-07-11-literature-tracking-service-redesign-design.md` | accepted | 文献追踪产品和服务重设计 |
| `2026-07-11-openscience-console-design.md` | accepted | OpenScience WebUI 品牌、导航和外壳 |
| `2026-07-11-osci-design-system-design.md` | accepted | 前端设计系统；`osci` 不替代内部 `ainrf` 身份 |
| `2026-07-11-project-task-workspace-domain-design.md` | accepted | 当前核心领域关系设计 |
| `2026-07-17-codex-aligned-conversation-domain-design.md` | accepted / implementation active | Task/Turn/Item 目标领域模型；剩余 cutover 由 2026-08-01 闭合 Spec 跟踪 |
| `2026-07-17-conversation-domain-standalone-migration-design.md` | proposed | 等待 schema 冻结的数据迁移设计 |
| `2026-07-17-engine-runtime-and-credential-injection-design.md` | accepted / awaiting implementation | Engine runtime 与 credential 目标设计 |
| `2026-08-01-conversation-domain-cutover-closure-design.md` | in-progress | 闭合 Task/Attempt 到 Task/Turn/Item/Submission/Execution/Binding 的产品切换 |
| `2026-08-01-literature-transport-contract-design.md` | proposed | 以 Pydantic/OpenAPI 收口 Literature transport Interface、frontend Adapter 与 legacy retirement |

已实现、被替代、退役或与当前 contract 冲突的设计位于 [`archived/`](archived/README.md)。
