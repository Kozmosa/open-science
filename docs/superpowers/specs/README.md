# Active design specifications

本目录只保存仍在决策或实施中的 OpenScience 设计。当前产品事实以代码、测试、`PROJECT_BASIS.md` 和 `docs-site/docs/` 为准；生命周期规则见 [`../../documentation-governance.md`](../../documentation-governance.md)。

## Active inventory

| Spec | 状态 | 说明 |
| --- | --- | --- |
| `2026-07-11-five-layer-hybrid-ci-design.md` | accepted / partially implemented | L0/L1 已落地，L2–L4 仍定义后续验证边界 |
| `2026-07-11-literature-tracking-service-redesign-design.md` | accepted | 文献追踪产品和服务重设计 |
| `2026-07-11-openscience-console-design.md` | accepted | OpenScience WebUI 品牌、导航和外壳 |
| `2026-07-11-osci-design-system-design.md` | accepted | 前端设计系统；`osci` 不替代内部 `ainrf` 身份 |
| `2026-07-11-project-task-workspace-domain-design.md` | accepted | 当前核心领域关系设计 |
| `2026-07-17-codex-aligned-conversation-domain-design.md` | accepted / awaiting implementation | Task/Turn/Item 目标领域模型 |
| `2026-07-17-conversation-domain-standalone-migration-design.md` | proposed | 等待 schema 冻结的数据迁移设计 |
| `2026-07-17-engine-runtime-and-credential-injection-design.md` | accepted / awaiting implementation | Engine runtime 与 credential 目标设计 |
| `2026-07-30-compatibility-telemetry-correctness-design.md` | accepted / awaiting implementation | 区分长期与 cleanup-only 遥测，修复 compatibility 流量漏算、误算和混算 |

已实现、被替代、退役或与当前 contract 冲突的设计位于 [`archived/`](archived/README.md)。
