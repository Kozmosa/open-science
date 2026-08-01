---
doc_state: current
status: in-progress
last_reviewed: 2026-08-01
review_by: 2026-08-31
---

# Conversation Domain Cutover 闭合设计

**Status:** In progress — core persistence and application implementation exists on `feat/conversation-domain-v3`; transport/runtime/migration cutover is incomplete
**Date:** 2026-08-01
**Scope:** 将当前 Task/Attempt/RuntimeSession 产品行为闭合迁移为已接受的 Task/Turn/Item/Submission/Execution/Binding 模型
**Depends on:** [`2026-07-17-codex-aligned-conversation-domain-design.md`](2026-07-17-codex-aligned-conversation-domain-design.md)、[`2026-07-17-engine-runtime-and-credential-injection-design.md`](2026-07-17-engine-runtime-and-credential-injection-design.md)、[`2026-07-17-conversation-domain-standalone-migration-design.md`](2026-07-17-conversation-domain-standalone-migration-design.md)

## 1. 目的

已接受的 Conversation Domain 规定 Task 等同 Codex Thread，Turn 是用户执行边界，Item 是对话/工具/审批/文件变化记录，可靠性由 TurnSubmission 与 RuntimeExecution 承担。当前 `origin/master` 仍以 TaskAttempt、RuntimeSession、pause/resume/continue 和扁平 output 为 product authority。

本 Spec 不重新设计领域语义，而是拥有从“核心结构已开始实现”到“正式 product cutover 完成”的剩余闭合工作，避免出现第三套长期模型或只完成 schema、不迁移 caller 的半成品。

## 2. 当前基线

`origin/master` 当前事实：

- `TaskApplicationService` 是唯一 Task lifecycle writer；
- `agent_task_attempts`、`agent_runtime_sessions`、`task_attempt_control_requests` 仍承担正式 runtime；
- HTTP 仍暴露 pause、resume、continue、retry；
- Harness Interface 仍暴露 `pause()`、`resume()`、`send_input()`；
- Runs/usage/project projections 仍以 Attempt 为主要统计结构；
- Conversation accepted spec 明确标记等待实现。

现有 `feat/conversation-domain-v3` worktree 已形成 6,300+ 行在途实现，包括：

- conversation contracts；
- TaskTurn、TurnItem、EngineConversationBinding persistence；
- TurnSubmission、RuntimeExecution、control/approval/fork persistence；
- Conversation application Module；
- repository 与 application tests。

这些在途提交尚未进入 `origin/master`，不能被公开文档称为当前 contract；但后续实现应在该基础上闭合，而不是另起一套模型。

## 3. 权威与不变量

1. 任一时刻只有一个 product write authority；不长期 dual-write TaskAttempt 与 Turn。
2. Expand 阶段可写 shadow/new tables，但正式读取与用户行为必须有明确 authority marker。
3. Task business status 与 Turn/runtime status 分离。
4. `pause` 退役；停止 active execution 的正式语义是 interrupt 当前 Turn。
5. idle Task 的新输入创建新 Turn；active Turn 的追加输入才是 steer。
6. Retry 创建新 Turn，并记录 `retry_of_turn_id`；worker recovery 不创建用户 Turn。
7. RuntimeExecution、submission 和 control delivery unknown 必须显式保存，不能谎报成功或重新发送用户输入。
8. Item 是正式 transcript Interface；不得继续把所有事件压成 `kind + content` 字符串。
9. SQLite 是 local-substitutable dependency，persistence seam 保持在深 Conversation Module 内部。

## 4. 目标 Module

```text
ConversationApplicationModule
  Interface:
    create_task
    submit_turn
    steer_active_turn
    interrupt_active_turn
    retry_turn
    fork_task
    read_task / list_turns / list_items

  Internal implementation:
    conversation repository
    execution repository
    idempotency and authorization
    Task/Turn state transitions
    submission/outbox
    binding and fork receipts
```

Worker 使用私有 execution Interface：claim submission、mark delivery、open/finish execution、append Item、consume control、reconcile unknown。HTTP、页面和普通 application caller 不获得该 Interface。

Harness/driver 位于 runtime Seam：Codex App Server、Claude Agent SDK 和 Claude CLI Adapter 明确报告 native/emulated/degraded/unsupported，不污染共同 Interface。

## 5. Cutover 阶段

### C1：核心结构闭合

- 冻结 contracts、表、索引、约束和 typed errors；
- 通过正式 Conversation Interface 测试，而不是只测 repository；
- 明确 authority marker 与 schema/version fuse；
- 确认 in-progress 分支不引入 API/Pydantic 反向依赖。

### C2：Runtime Adapter

- Codex 使用 thread/turn/item 与 native steer/interrupt；
- Agent SDK 将 live input/interrupt 映射到同一 causal contract；
- Claude CLI 不伪造 same-turn steer；active 输入保存为 next-turn intent；
- 删除共同 Harness Interface 中错误的 pause/resume 语义；
- engine-specific session/binding 只由对应 Adapter 拥有。

### C3：HTTP 与 generated transport

- `/api/tasks` 保持正式 Task aggregate 入口；
- 增加 Turn/Item、steer、interrupt、approval、fork preview/confirm Interface；
- 删除 pause/resume；将 continue 收敛为 submit Turn；
- Pydantic/OpenAPI 是唯一 transport authority；
- frontend generated transport、feature Adapter、MSW 与 UI 同批迁移。

### C4：Worker 与 projection cutover

- dispatch 从 Attempt/outbox 切到 TurnSubmission/RuntimeExecution；
- stream、messages、output 切到 ordered Item projection；
- Runs、Timeline、usage 与 Project usage 内部切到 Turn/RuntimeExecution；
- 保持这些页面的用户职责，不保留 Session 资源。

### C5：Standalone migration

- 按既有 migration spec 从不可变 snapshot 推断旧 Attempt/RuntimeSession/output；
- 无法证明的边界写 `legacy_inferred` provenance；
- shadow destination → verify → cutover；
- active/unknown execution 必须先 drain、interrupt 或人工处理；
- secret 只进入 CredentialStore，不进入 Turn/Item/report。

### C6：Contract 与删除

- 停止旧 writer 和读 fallback；
- 删除 pause/resume、Attempt 用户语义和 RuntimeSession product projection；
- migration/admin read-only evidence 按明确保留期保留；
- 更新 `PROJECT_BASIS.md`、architecture docs 和 active spec lifecycle；
- 完成隔离 release acceptance 后才将本 Spec 归档。

## 6. 与 `agentic_researcher` 的关系

`agentic_researcher` 不恢复为 Task CRUD facade。研究员 preset 与当前兼容数据模型可以在迁移期间保留；Conversation application Interface 继续由 Domain 拥有。若迁移后旧 Task/engine dataclass 无 caller，应通过 deletion test 删除或迁移到明确 owner，而不是增加 pass-through facade。

## 7. 测试策略

- contracts：状态机、因果约束、非法转换；
- application Interface：submit/steer/interrupt/retry/fork/idempotency/permission；
- SQLite stand-in：事务、唯一约束、crash recovery；
- driver Adapter contract：Codex、Agent SDK、CLI capability matrix；
- HTTP contract：Pydantic/OpenAPI/generated transport；
- migration：真实旧 fixture、unknown/partial provenance、reconciliation；
- concurrency：同 Task 单 active Turn、重复提交、control races；
- release：Task 创建、多 Turn、steer、interrupt、retry、fork、restart persistence。

测试以正式 Interface 为主。repository tests 可以保留关键 SQL invariant，但不能成为唯一行为证据。

## 8. 验收条件

- Task/Turn/Item 是唯一正式 conversation truth。
- 普通产品路径不读写旧 Attempt/RuntimeSession；migration/admin-only surface 明确隔离。
- pause/resume 从 HTTP、frontend、Harness 共同 Interface 和文档删除。
- active steer 带 expected turn causal guard；unsupported Adapter 不谎报成功。
- stream 与历史由 Item projection 得出。
- worker recovery 不生成额外用户 Turn。
- generated transport、MSW、frontend tests 和真实 HTTP contract 一致。
- L1 通过；隔离 release acceptance 覆盖 restart、权限与完整用户流程；不操作 production 取证。

## 9. 非目标

- 不改变 Project、Workspace、Environment、Context 的已接受关系。
- 不把 Task 改名为 Thread。
- 不在本轮重做所有页面视觉。
- 不建设长期 dual-read/dual-write compatibility layer。
- 不因在途分支存在就跳过 migration、transport 或 release cutover 证据。
