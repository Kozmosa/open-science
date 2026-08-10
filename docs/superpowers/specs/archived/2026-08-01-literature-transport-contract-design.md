---
doc_state: archived
status: implemented
last_reviewed: 2026-08-01
review_by: 2026-08-31
---

# Literature Transport Contract 收口设计

**Status:** Implemented and archived on 2026-08-01
**Date:** 2026-08-01
**Scope:** `/api/literature` 的 Pydantic/OpenAPI schema、generated frontend transport、feature Adapter、MSW contract 和 legacy route retirement
**Depends on:** [`2026-07-11-literature-tracking-service-redesign-design.md`](../2026-07-11-literature-tracking-service-redesign-design.md)

> [!success] 实施结果
> 19 个 accepted operations 已建立 Pydantic/OpenAPI Interface、generated frontend transport、feature Adapter 与 MSW contract；SQLite version row 已通过显式 presenter 白名单隔离。7 个 legacy operations 已收敛为正式 application Interface 上的 compatibility Adapter，但因没有独立删除批准而 fail-closed 保留。当前 inventory 已提升到 `docs/reference/literature-transport-contract.md` 与 `docs-site/docs/architecture.md`。

## 1. 问题与证据

`PROJECT_BASIS.md` 规定 FastAPI/Pydantic OpenAPI 是唯一 transport schema authority。当前 Literature router 有 26 个 HTTP operations，但：

- OpenAPI request body schema 为 0；
- success response schema 为 0；
- 多数 route 直接 `await request.json()` 并返回 `dict`；
- frontend 在 `shared/types/index.ts` 手写 Literature transport-like types；
- MSW contract 证明 Mock 与手写前端类型一致，不能证明其与 backend 一致；
- `get_paper()` 将 SQLite version row 直接 `dict()` 返回，存在 persistence shape 泄露。

26 个 operations 中，19 个属于新正式 Interface，7 个是活跃 Spec 已声明为迁移期兼容的 subscriptions/fetch/read routes。当前新旧路径仍分别调用 `LiteratureTrackingService` 与 `LiteratureService`，并通过 `sync_legacy_topic()` 协调，不是纯 pass-through compatibility Adapter。

## 2. 决策

1. 保持 FastAPI/Pydantic OpenAPI 唯一 authority，不为 Literature 建例外。
2. 先冻结现有有效行为，再增加 schema；不把 contract 收口与产品重设计混成一次变更。
3. transport schema、frontend view model 和 persistence row 明确分离。
4. 19 个正式 operations 全部使用 typed request/response；7 个 legacy routes 单独 inventory、验证和删除。
5. compatibility removal 使用 caller audit、自动验证、隔离环境手动验收和用户批准，不要求为了 telemetry 将未验收代码部署到 production。

## 3. Interface inventory

### 3.1 正式 Interface

- overview：1；
- topics：6；
- checks：4；
- papers/detail/state：3；
- summary：2；
- research-task：3（create、list、按 idempotency key 查询）。

实施时应对照 accepted Literature Spec 补齐或显式裁决：

- `GET /papers/{paper_id}/versions`；
- `summary_status`、`has_research_task` filters；
- 所有分页列表的 `{items,total,next_cursor}`；
- Summary `stale` 状态；
- singular research-task 查询是否继续作为正式 Interface。

### 3.2 Legacy inventory

- `GET/POST /subscriptions`；
- `PUT/DELETE /subscriptions/{subscription_id}`；
- `GET .../fetch-status`；
- `POST .../fetch`；
- `POST /papers/{paper_id}/read`。

`/convert` 已删除，不得恢复。

## 4. Schema ownership

按业务 owner colocate schema：

```text
literature transport
  overview schemas
  topic schemas
  check schemas
  paper/version/state schemas
  summary schemas
  research-task schemas
  compatibility schemas          # 仅迁移期
```

禁止把全部模型继续堆入跨领域 `api/schemas.py`。Router、presenter 和 schema 可以按上述 owner 分文件，但外部 `/api/literature` Interface 保持稳定。

所有成功响应必须声明 `response_model` 或等价 typed return。204 route 不返回 body。错误继续使用统一 HTTP error contract。

## 5. Domain 与 presenter Seam

Literature application Module 返回 typed domain result 或内部 dataclass，不返回 transport Pydantic model，也不直接返回 SQLite row。

Presenter 负责：

- enum 与时间格式；
- nullable/optional 收敛；
- pagination envelope；
- persistence 字段白名单；
- research-task saga 状态映射；
- legacy payload mapping。

这样 transport 改动集中于 Adapter，SQLite schema 改动不会自动扩大 HTTP Interface。

## 6. Frontend 迁移

```text
generated Literature transport
  → features/literature Adapter
    → Literature view models
      → page/components
```

要求：

- 删除 `shared/types/index.ts` 中重复的 transport payload；
- UI-specific view、filter draft 和 derived display model 可以手写；
- feature Adapter 显式处理 nullable、enum、pagination 和 research intent；
- paths/methods 使用 generated operation metadata 或 typed client，不继续手写全部 URL；
- production build 同样受 operation binding 检查，不仅 DEV assertion；
- MSW handlers 使用 generated request/response types。

## 7. 分阶段实施

### L1：冻结与 contract matrix

- 为 26 个 operations 记录 method、path、auth、request、success、error、caller 和 owner；
- 捕获当前有效响应 fixture，但不把内部多余字段提升为永久 contract；
- 增加 malformed JSON、wrong type、unknown enum、missing idempotency key 测试；
- 明确 19 formal / 7 legacy。

### L2：正式 schema

- 从 topic/check 开始，再迁移 paper/version/state、summary、research-task；
- 每批同步 OpenAPI、generated artifact 和 backend contract tests；
- presenter 禁止 persistence row 泄露；
- 补齐 accepted Spec 中确认保留的缺失 Interface。

### L3：frontend generated Adapter

- 迁移 feature API 和 view model；
- 更新 React Query caller；
- 更新 MSW scenario 和 contract tests；
- 删除重复 shared transport types。

### L4：legacy compatibility

- 将 legacy route 收敛为只调用正式 Literature application Interface 的 Adapter；
- 禁止 legacy 与新 Module 维护两套写规则；
- repo、generated、frontend、script caller audit；
- 隔离 release 手动验收后，由用户逐批批准删除；
- 更新 architecture compatibility inventory。

## 8. 测试与验收

- 19 个正式 operations 都有 request/success OpenAPI schema；
- generated manifest 能识别 Literature schemas 与 operation mapping；
- backend contract tests 通过真实 HTTP Interface；
- malformed JSON 不产生 500；
- SQLite 新列不会未经 presenter 自动出现在响应；
- frontend 不再手写 Literature transport payload；
- MSW 与 backend 共用 generated contract；
- pagination、status enum、idempotency 和权限语义与 accepted Literature Spec 一致；
- legacy 删除前后都有明确 caller 与 404 evidence；
- L1、frontend test/build、transport drift 和 docs build 通过。

## 9. 非目标

- 不重选 Dramatiq/Redis/SQLite 技术栈。
- 不重做 Literature 页面视觉。
- 不把 Literature 数据迁入 Domain SQLite。
- 不把 schema model 当 Domain model。
- 不在 contract 收口中顺手删除未经用户批准的 compatibility routes。
