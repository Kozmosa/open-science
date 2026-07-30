# Archived design specs

本目录保存已被当前产品契约明确取代、但仍有历史和迁移参考价值的设计说明。

这些文档不是当前实现依据。Agent、实现计划和代码 review 必须优先读取 `PROJECT_BASIS.md`、`docs-site/docs/`、代码和 [`../README.md`](../README.md) 中的活跃设计清单；归档文档只能用于理解旧数据、旧接口和迁移来源。

归档文档保留当时的原始判断。即使其中曾明确主张某个后来被推翻的方向，也不通过重写历史来伪装一致性；统一的历史 warning、归档位置和后继文档负责说明其当前效力。例如，过去把 `ainrf` package、状态路径或运行时身份视为待全量替换债务的判断，已经被当前“OpenScience 品牌 + 稳定 ainrf 工程身份”约定取代。

## 归档批次

- 2026-04 至 2026-06 增量设计：已实现的 UI、runtime、auth、skills、performance、docs、deployment 和 observability 设计，稳定事实已进入代码、测试、当前参考文档或后继设计。
- 2026-07-11 领域设计归档批次：被当前 Project / Task / Workspace 契约取代的 Session、Retry 和权限设计。
- 2026-07-12 领域执行规范：大部分执行阶段已完成，剩余 Conversation/Runtime 方向由 2026-07-17 活跃 spec 接管。
- 2026-07-29 架构清理设计：P0–P6 已完成，当前架构 contract 已提升到 `docs-site/docs/architecture.md` 和 `PROJECT_BASIS.md`。

## 2026-07-11 领域设计归档批次

当前替代入口：[`../2026-07-11-project-task-workspace-domain-design.md`](../2026-07-11-project-task-workspace-domain-design.md)

- `2026-05-17-ainrf-session-chain-design.md`：旧的独立 Session/Attempt 用户模型；由唯一 Task → Attempt → Runtime Session 模型取代。
- `2026-06-02-task-retry-design.md`：旧的“归档并克隆 Task” Retry；由同一 Task 下 Attempt 语义取代。
- `2026-06-03-task-retry-e2e-design.md`：依赖旧 Retry response 和新 Task 选择行为的测试设计。
- `2026-06-15-permission-and-visibility-management.md`：旧 Project collaborator、Workspace 单归属和删除权限模型；由新权限能力表与关联不变量取代。
