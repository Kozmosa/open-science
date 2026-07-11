# Archived design specs

本目录保存已被当前产品契约明确取代、但仍有历史和迁移参考价值的设计说明。

这些文档不是当前实现依据。Agent、实现计划和代码 review 必须优先读取 `docs/superpowers/specs/` 根目录中的 Accepted 设计；归档文档只能用于理解旧数据、旧接口和迁移来源。

## 2026-07-11 领域设计归档批次

当前替代入口：[`../2026-07-11-project-task-workspace-domain-design.md`](../2026-07-11-project-task-workspace-domain-design.md)

- `2026-05-17-ainrf-session-chain-design.md`：旧的独立 Session/Attempt 用户模型；由唯一 Task → Attempt → Runtime Session 模型取代。
- `2026-06-02-task-retry-design.md`：旧的“归档并克隆 Task” Retry；由同一 Task 下 Attempt 语义取代。
- `2026-06-03-task-retry-e2e-design.md`：依赖旧 Retry response 和新 Task 选择行为的测试设计。
- `2026-06-15-permission-and-visibility-management.md`：旧 Project collaborator、Workspace 单归属和删除权限模型；由新权限能力表与关联不变量取代。
