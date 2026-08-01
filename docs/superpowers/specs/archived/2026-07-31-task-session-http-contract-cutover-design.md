---
doc_state: archived
status: implemented
last_reviewed: 2026-07-31
review_by: 2026-08-30
---

# Task / Session 正式 HTTP 契约收口与兼容面退役设计

> 本文已实现并归档，不再定义当前产品 contract。当前事实见 [`docs-site/docs/architecture.md`](../../../../docs-site/docs/architecture.md)、代码、generated transport 与契约测试。

**Status:** Implemented
**Date:** 2026-07-31  
**Scope:** Task 正式 HTTP Interface、Project 下的 Task relationship / usage 投影、WebUI 迁移、Session 兼容投影删除、Task 兼容字段和旧入口删除、遥测与文档收口  
**Depends on:** [`2026-07-11-project-task-workspace-domain-design.md`](../2026-07-11-project-task-workspace-domain-design.md) 的 Project / Workspace / Task 关系，以及 [`2026-07-17-codex-aligned-conversation-domain-design.md`](../2026-07-17-codex-aligned-conversation-domain-design.md) 对 Task / Turn / Item 的最终语义
**Related current contract:** [`docs-site/docs/architecture.md`](../../../../docs-site/docs/architecture.md)
**Removal authority:** 用户已明确接受“当前没有外部调用者”的人工判断；本设计仍要求完成 caller 迁移、契约测试和 release staging 人工验收，但不要求操作 production

## 1. 决策摘要

本轮不新建“正式 Session 资源”，也不新建 `/api/domain/tasks` 第二套 Task 路由。

最终决策是：

1. `/api/tasks` 是唯一正式 Task HTTP Interface；
2. Task 列表使用 `project_id` 筛选，不再保留 `/api/projects/{project_id}/tasks` 转发入口；
3. Project 拥有的 Task relationship 和 usage summary 进入 `/api/domain/projects/{project_id}/...`；
4. 管理界面展示 Task 及其执行历史，不再将 Task 伪装成独立 Session；
5. `/api/sessions` 整组投影、`SessionProjectionService` 和专用 schema 全部删除；
6. Task create / fork / retry 统一返回一个结构化 mutation 结果，不再保留 flat response、`new_task` 或重复的 retry response schema；
7. Task 创建只接受 Workspace，`environment_id` 由 Workspace 确定；写操作只接受 `Idempotency-Key` header；
8. 先建立正式 Interface 并迁移 caller，通过删除前验证后，才删除旧入口和旧格式；
9. 本轮不实现 Turn / Item 数据模型，不重新定义 pause / resume / continue 语义。这些由已接受的 Conversation Domain 设计接管。

### 1.1 非目标

本轮不：

- 实现 Task / Turn / Item 持久化迁移；
- 修改 durable Task / Attempt / RuntimeSession 表结构；
- 重新设计 engine runtime、credential injection 或 worker recovery；
- 将管理侧运行记录变成新的用户会话聚合；
- 操作 production 容器、production HTTP、production 日志或 production 数据；
- 为未来可能的外部 caller 保留新的临时 alias；
- 修改 `PROJECT_BASIS.md`。

## 2. 当前问题

### 2.1 Session 是浅层兼容 Module

当前 `/api/sessions` 并没有独立的权威数据：

- Session ID 实际就是 Task ID；
- Session 列表是 Task 列表的改名投影；
- Session detail 是 Task + TaskAttempt 的重新包装；
- POST / PATCH / DELETE 始终返回 405；
- WebUI 的 Sessions 页面已经直接读取 Task，旧 `features/sessions/api.ts` 没有正式 caller。

按 deletion test，删除该 Module 后不会迫使复杂度扩散到 caller，反而会同时删除重复 schema、序列化、权限查询和测试。因此它是应被退役的浅层兼容 Module，不是应被提升的正式 Interface。

### 2.2 Task 后端已基本正式化，caller 和 schema 仍然混用旧契约

当前 `/api/tasks` 已经通过 `TaskApplicationService` 和 `TaskProjectionService` 读写 committed-v2 state，但仍有以下问题：

- Frontend `createTask` 和 `forkTask` 声明返回 flat `TaskSummary`，而后端实际返回 `{task, attempt, dispatch}`；
- Retry 已返回结构化结果，但 Mock 和测试仍保留 `new_task` fallback；
- Frontend 手写 `TaskCreatePayload` 仍允许 `environment_id`；
- `TaskRetryResponse` 与 `TaskMutationResponse` 表达同一结构，增加了无必要 Interface；
- `/api/tasks/{task_id}/project` 只是 `/move` 的 deprecated alias；
- `/api/tasks/{task_id}/permanent` 永远返回 410，不是可用能力；
- Project 下的 Task list、Task edge 和 cost summary 仍挂在已删除资源 Interface 的兼容 router 上；
- Project cost response 仍使用 `session_count`，Task relationship 仍使用 `edge_id` 和 `task-edges` 旧术语；
- Frontend 重复定义 Task / Session transport 类型，容易与 generated contract 偏离。

### 2.3 不能把过渡 Attempt 语义重新冻结成长期 Session 契约

[`2026-07-17-codex-aligned-conversation-domain-design.md`](2026-07-17-codex-aligned-conversation-domain-design.md) 已决定最终模型是 Task / Turn / Item / RuntimeExecution。本轮可以继续使用当前 TaskAttempt 读投影支持运行历史，但不得：

- 新建 `/api/domain/sessions`；
- 把 Attempt 重命名为新的长期 Session；
- 为了删除旧路由而重复创建一套将来还要删除的 transport schema；
- 借兼容清理之名提前实现不完整的 Turn 子集。

## 3. 目标 Interface

### 3.1 Task HTTP Interface

Canonical prefix 继续是 `/api`。Task 的唯一外部 seam 是 `/api/tasks`。

| 方法 | 路径 | 请求 / 响应 | 决策 |
| --- | --- | --- | --- |
| GET | `/api/tasks` | `TaskListResponse` | 正式列表，支持 `project_id`、`include_archived`、`limit`、`sort` |
| POST | `/api/tasks` | `TaskCreateRequest -> TaskMutationResponse` | 正式创建 |
| GET | `/api/tasks/{task_id}` | `TaskSummaryResponse` | 正式详情 |
| PATCH | `/api/tasks/{task_id}` | `TaskUpdateRequest -> TaskSummaryResponse` | 只修改明确可变元数据 |
| GET | `/api/tasks/{task_id}/attempts` | `TaskAttemptListResponse` | 当前运行历史读投影，后续由 Turn 迁移接管 |
| POST | `/api/tasks/{task_id}/retry` | `TaskMutationResponse` | 统一 mutation response，不接受 body |
| POST | `/api/tasks/{task_id}/fork` | `TaskForkRequest -> TaskMutationResponse` | 统一 mutation response |
| POST | `/api/tasks/{task_id}/move` | `TaskMoveRequest -> TaskSummaryResponse` | 唯一 Project move 入口 |
| POST | `/api/tasks/{task_id}/archive` | `TaskSummaryResponse` | 保留 |
| POST | `/api/tasks/{task_id}/unarchive` | `TaskSummaryResponse` | 保留 |
| POST | `/api/tasks/{task_id}/cancel` | 204 | 当前取消入口，frontend 不得当作 Task 响应解析 |
| GET | `/api/tasks/{task_id}/output` | `TaskOutputResponse` | 保留当前输出投影 |
| GET | `/api/tasks/{task_id}/messages` | `TaskMessagesResponse` | 保留当前会话展示投影 |
| GET | `/api/tasks/{task_id}/stream` | SSE | 保留，由单独 stream contract test 约束 |

`pause`、`resume`、`continue` 及 launch-unknown 管理入口在本轮保持现状，不被宣布为最终长期语义。它们必须在 Turn / interrupt / steer 实现时由 Conversation Domain spec 统一处理，不得在本轮删除后用另一套临时别名替代。

### 3.2 Task list 契约

当前产品规模不需要为 Task 列表建立一套尚未实现的 cursor protocol。本轮选择小而真实的 Interface：

```json
{
  "items": [],
  "total": 0
}
```

规则：

- `limit` 是有界上限，默认 200，最大 1000；
- `sort` 只允许冻结值，不把任意 SQL 或字段名暴露给 caller；
- `project_id` 是正式筛选条件，替代 `/api/projects/{project_id}/tasks`；
- Frontend 删除并未被后端实现的 `cursor` / `has_more` 假契约；
- 如未来真实数量需要 cursor，应单独设计并一次性在后端、generated contract 和 caller 落地。

### 3.3 结构化 mutation response

Task create、fork 和 retry 共用一个 response schema：

```json
{
  "task": {},
  "attempt": {},
  "dispatch": {}
}
```

约束：

- `task`、`attempt`、`dispatch` 都是必填；
- 删除重复的 `TaskRetryResponse`，retry 直接使用 `TaskMutationResponse`；
- 不发送 flat Task 字段；
- 不发送 `new_task`；
- Frontend feature Adapter 根据交互需要返回 `response.task` 或完整 mutation view model，UI 不直接假定 raw response 就是 Task；
- MSW 只伪造该正式结构，不再伪造 flat / `new_task` 变体。

### 3.4 Task create request

```json
{
  "project_id": "project-id",
  "workspace_id": "workspace-id",
  "researcher_type": "vanilla",
  "harness_engine": "codex-app-server",
  "prompt": "...",
  "skills": [],
  "mcp_servers": [],
  "title": "optional"
}
```

约束：

- `project_id` 不得以空字符串表示“稍后校验”，应在 schema 层 `min_length=1`；
- `workspace_id` 必填；
- 不接受 `environment_id`；
- `prompt` 是当前 bridge 契约的用户输入，未来会迁移到初始 Turn，本轮不提前发明 Turn payload；
- Frontend 使用 generated request type，不手写包含额外字段的 transport type。

### 3.5 Project-owned Task relationship Interface

Task relationship 属于 Project 聚合视图，放在 Project 的正式 seam：

| 方法 | 路径 |
| --- | --- |
| GET | `/api/domain/projects/{project_id}/task-relationships` |
| POST | `/api/domain/projects/{project_id}/task-relationships` |
| DELETE | `/api/domain/projects/{project_id}/task-relationships/{relationship_id}` |

新 schema 使用领域术语：

```json
{
  "relationship_id": "...",
  "project_id": "...",
  "source_task_id": "...",
  "target_task_id": "...",
  "relationship_type": "related_to",
  "created_at": "..."
}
```

要求：

- Module Interface 继续使用 `list/create/delete_task_relationship` 能力；
- HTTP Adapter 不再把 `relationship_id` 改名为 `edge_id`；
- 删除 `/api/projects/{project_id}/task-edges` 和 `/api/task-edges/{edge_id}`；
- Frontend canvas Adapter 映射 relationship view model，如果 UI 内部仍使用“edge”作图形术语，不得反向泄漏成 transport schema。

### 3.6 Project usage summary Interface

Project 用量属于 Project 的可见投影：

```text
GET /api/domain/projects/{project_id}/usage-summary
```

返回：

```json
{
  "project_id": "...",
  "task_count": 0,
  "attempt_count": 0,
  "total_duration_ms": 0,
  "total_cost_usd": 0.0,
  "total_tokens": 0,
  "by_model": {}
}
```

决策：

- 用 `usage-summary` 替代只表达金额的 `cost-summary`；
- 用 `task_count` / `attempt_count` 替代含义错误的 `session_count`；
- 所有值继续从权威 Task / TaskAttempt 投影得出，不得恢复读取旧 sessions database；
- 未来 TaskAttempt 迁移为 Turn / RuntimeExecution 时，保持 Project usage Interface，只更换内部 Implementation。这是一个有深度和长期 leverage 的 Module。

## 4. Session 能力迁移与退役

### 4.1 能力对应

| 旧入口 | 正式能力 | 处理 |
| --- | --- | --- |
| `GET /api/sessions` | `GET /api/tasks` | caller 已迁移，删除 |
| `GET /api/sessions/{session_id}` | `GET /api/tasks/{task_id}` | caller 已迁移，删除 |
| `GET /api/sessions/{session_id}/attempts` | `GET /api/tasks/{task_id}/attempts` | 迁移后删除 |
| `GET /api/sessions/batch-detail` | 无 | 无 caller，直接删除 |
| `POST /api/sessions` | 无 | 当前仅 405，删除 |
| `PATCH /api/sessions/{session_id}` | 无 | 当前仅 405，删除 |
| `DELETE /api/sessions/{session_id}` | 无 | 当前仅 405，删除 |

### 4.2 代码删除清单

在 caller 验证通过后删除：

- `src/ainrf/api/routes/sessions.py`；
- `SessionProjectionService` 及 lazy export / app state 装配；
- `SessionResponse`、`SessionDetailResponse`、`SessionListResponse`、`AttemptResponse`、`AttemptListResponse`；
- `frontend/src/features/sessions/api.ts`；
- frontend 中手写的 Session / legacy Attempt transport types；
- Session compatibility MSW handlers 和 state helpers；
- 只验证 Session 投影转发的测试；
- `legacy_session` write-attempt telemetry 与只为 405 路由存在的测试。

`AttemptProjectionService` 不删除，因为 Task detail、Task attempt history、token usage 和 Project usage summary 仍然共用它。应修正其中“compatibility Session”类过时注释，但不因本轮进行无意义拆分。

### 4.3 WebUI 术语收口

当前管理页展示的是 Task 而不是 Session。实现时必须：

- 将导航和页面名称改为“运行记录” / `Runs`；
- 将前端路由从 `/sessions` 改为 `/runs`；
- 在当前无外部 caller 的人工判断下，不保留 `/sessions` 前端 redirect；
- 将 `features/sessions/` 重命名为表达页面职责的 `features/runs/`；
- 页面列表读取 Task，详情读取 Task，执行历史读取 TaskAttempt；
- 不把 TaskAttempt 重命名为 Session，不展示虚构的 session count。

## 5. Frontend Adapter 与类型治理

### 5.1 generated transport 是唯一 transport schema authority

Frontend 不得在 `shared/types` 或 feature 内重复手写以下 transport type：

- Task create request；
- Task mutation response；
- Task retry response；
- Session list / detail / Attempt list；
- Task relationship HTTP response；
- Project usage summary HTTP response。

正确依赖方向：

```text
generated transport
  -> feature Adapter
  -> Task / Run / Project view model
  -> page and UI
```

UI 不直接消费 raw generated payload。Adapter 必须明确完成：

- mutation response 解包；
- relationship 到 canvas edge view model 的映射；
- nullable / optional 字段收敛；
- Task status 和显示文案的局部映射。

### 5.2 必须修正的已知类型错误

- `createTask` 不得把 `TaskMutationResponse` 当作 `TaskSummary`；
- `forkTask` 不得把 `TaskMutationResponse` 当作 `TaskSummary`；
- `cancelTask` 不得把 204 当作 `TaskSummary`；
- `pauseTask` / `resumeTask` 在保留期必须使用实际 response type，不通过一个错误的通用 `taskAction` 类型掩盖差异；
- `TaskCreatePayload.environment_id` 必须删除；
- retry Mock / tests 中的 `new_task` fallback 必须删除；
- `TaskListResponse.has_more` / `next_cursor` 假契约必须删除。

## 6. 幂等、权限、错误和可观测性

### 6.1 幂等

- 所有 Task / relationship 写入只接受 `Idempotency-Key` header；
- 不接受 body 或 query 中的 idempotency alias；
- 相同 actor、scope、key 和请求内容必须返回同一结果；
- 同 key 不同内容必须 409；
- Frontend key 在请求不确定时保持稳定，只在成功后轮换。

### 6.2 权限

- Task list / detail / attempt history 使用 Task / Project viewer 可见性；
- Task update / archive / move / retry / fork 继续使用现有 Task / Project / Workspace 权限规则；
- Task relationship list 要求 Project viewer，create / delete 要求 Project editor；
- Project usage summary 要求 Project viewer；
- 不可见资源不得通过错误差异泄漏存在性。

### 6.3 错误契约

每个正式 Adapter 统一收敛：

- 400 / 422：请求格式或必填字段错误；
- 403：已确认资源但无权写入；
- 404：不可见或不存在；
- 409：状态冲突、幂等冲突或无效关系；
- 503：维护模式、cutover 未就绪或权威 Module 不可用；
- 不向 caller 暴露 SQLite、文件路径或运行时内部异常。

### 6.4 遥测

本轮优先使用长期 `ainrf_http_contract_requests_total` 确认新旧 operation，不为可由 operation 识别的路由另造 cleanup metric。

删除前需要记录：

- 新 Task / Project domain operation 已被 release staging UI 实际调用；
- 旧 Session / Project Task compatibility operation 没有 caller，或其调用仅来自明确的压测 / 验收；
- generated operation/path metadata 与实际路由一致；
- 遥测中不使用 Task ID、Project ID、prompt、token、path 或 idempotency key 作标签。

删除后同步清理：

- 已不再可能产生的 `flat_response`、`new_task`、`task_input`、Task create `environment_id` 分类代码和测试；
- `legacy_session` write-attempt metric；
- 仅为已删除路由添加的 deprecated headers 和 route registry；
- 已完成使命的临时 cleanup item。

## 7. 分阶段实施与双门禁

### Phase 0：契约清点与失败测试

1. 冻结旧入口和当前 caller inventory；
2. 为目标 Task / relationship / usage Interface 增加 HTTP contract tests；
3. 为前端 Adapter 增加 create / fork / retry / cancel 的精确 response tests；
4. 为旧 Session 客户端、`new_task` fallback、`environment_id` create field 和 Project compatibility 路径增加调用方检索清单；
5. 记录当前 generated transport 与 docs 差异，不改 `PROJECT_BASIS.md`。

### Phase 1：建立正式 Interface，暂时保留旧入口

1. 收紧 Task schemas 和返回格式；
2. 统一 Task mutation response；
3. 在 `/api/domain/projects` 建立 relationship 和 usage summary；
4. 让 `GET /api/tasks?project_id=...` 成为唯一 Project Task list 能力；
5. 旧 Session / Project compatibility 入口此时可以继续存在，但不允许新 caller 接入。

### Phase 2：迁移 WebUI、Mock 和 generated transport

1. Task feature Adapter 使用 generated transport type；
2. Project canvas 迁移到 task relationship Interface；
3. Project / runs 用量展示迁移到 usage summary；
4. Sessions 页改名 Runs，并只使用 Task / TaskAttempt；
5. 删除前端中对旧入口的调用，但暂不删后端旧路由；
6. 重建 generated transport，更新 MSW canonical handlers。

### Gate A：删除前验证

只有以下项目全部通过，才进入 Phase 3：

- caller scan 确认 frontend / scripts / tests / docs 不再使用旧 HTTP Interface；
- backend 新 Interface contract tests 通过；
- frontend lint、完整测试和 production build 通过；
- generated transport drift gate 通过；
- 完整 L1 通过；
- 构建一个不可变 release staging，人工完成 Task 创建、列表、详情、Retry、Fork、Move、Archive / Unarchive、Project relationship、Project usage 和 Runs 页验收；
- release staging 遥测显示上述 UI 使用新 operation；
- API / Web 日志无新增相关 5xx、schema validation 错误或资源权限错误。

Gate A 不要求 production 流量或 production 操作。本项目已按用户决策使用人工“当前无外部 caller”判断覆盖原完整生产观察窗口。

### Phase 3：删除旧格式、入口和浅层 Module

在 Gate A 通过后一次性删除：

- `/api/sessions/**`；
- `/api/projects/{project_id}/tasks`；
- `/api/projects/{project_id}/task-edges`；
- `/api/task-edges/{edge_id}`；
- `/api/projects/{project_id}/cost-summary`；
- `/api/tasks/{task_id}/project`；
- `/api/tasks/{task_id}/permanent`；
- Session projection Module、schemas、frontend client、Mock 和转发测试；
- `TaskRetryResponse`、`TaskRetryRequest`、`TaskUpdateProjectRequest`；
- flat mutation / `new_task` / create `environment_id` / retry `task_input` 的残留类型、Mock、测试和遥测分类；
- deprecated route headers 和无达成可能的 405 / 410 伪能力。

替换测试要遵守 replace-don't-layer：新 Interface 的测试已覆盖同一行为时，删除只证明旧 Adapter 转发的测试，不把它们保留成第二套契约。

### Phase 4：文档治理与删除后验证

1. 重新生成 transport，确认旧 paths / schemas 不在 OpenAPI 中；
2. 更新 `docs-site/docs/architecture.md` 的 HTTP contract 和 compatibility inventory；
3. 修订 `2026-07-11-project-task-workspace-domain-design.md` 中已被 Conversation Domain 取代的 Attempt / Session 陈述，明确 Turn 设计是后续 authority；
4. 核对 `2026-07-17-codex-aligned-conversation-domain-design.md` 中的过渡前提，只更新已被本轮实现改变的工程现状，不改写未实现的目标语义；
5. 更新 frontend 用户文档、导航截图说明或页面路由说明中的 Sessions 术语；
6. 将本 spec 移入 `docs/superpowers/specs/archived/`，状态记为 implemented，并更新 active inventory；
7. 更新当日 worklog，记录 Gate A、删除 commit、Gate B 和 release staging 结果。

### Gate B：删除后最终验收

必须全部通过：

- 新 Interface 功能与 Gate A 一致；
- 所有旧 API 路径返回 404；
- `/sessions` WebUI route 返回应用标准 not-found / redirect policy 中的非兼容结果，不再注册旧页面；
- 全仓 `rg` 无旧 route string、Session projection type、`new_task` fallback、Task create `environment_id` 和旧 Task edge transport 残留；
- Ruff、format、ty、backend full tests、transport check、frontend lint / tests / build、docs build 和 L1 全部通过；
- 用删除后 commit 重建不可变 release staging；
- 完整手工 UI / API 验收通过，无新增相关 4xx 误调用、5xx 或异常日志；
- 没有操作 production 容器、production HTTP、production 日志或 production 数据。

### Rollback

本轮预计不包含 durable schema migration，因此 rollback 以版本一致的整体 release artifact 为单位：

- Gate A 之前，旧入口仍在，可直接回退到当前 master 行为；
- Gate A 之后、Phase 3 之前，正式 caller 已迁移但旧入口仍在，可回退 frontend + backend 整体 artifact，不允许只回退一侧；
- Phase 3 之后，回退必须使用删除前的完整 manifest，不得临时恢复单个旧 router 或只恢复 frontend caller；
- 如实施中发现必须修改 durable schema，应停止本 spec 的删除阶段，先单独设计 migration / rollback，不得在本兼容清理中顺带实施；
- rollback 后重跑旧 release 的标准 read-only smoke，不以恢复旧兼容 telemetry 作为成功条件。

## 8. 必须的测试范围

### 8.1 Backend

- Task create 拒绝空 `project_id` 和额外 `environment_id`；
- create / fork / retry 返回完全相同的 mutation schema；
- retry 不接受兼容 body；
- Task list `project_id` 筛选、权限、limit 和 sort 正确；
- relationship list / create / delete 的权限、幂等和 schema 正确；
- usage summary 的 task / attempt / duration / token / cost 计算正确；
- 旧 Session / Project / Task aliases 在删除后均为 404；
- SessionProjectionService 和旧 schema 无 import / export 残留；
- 不可见 Task / Project 不泄漏存在性；
- read-only maintenance startup 下新 GET Interface 可用，写入继续被正确拒绝。

### 8.2 Frontend

- Task create 正确解包 `response.task`；
- Fork 正确选中新 Task；
- Retry 只读 `response.task`，没有 `new_task` fallback；
- Cancel 正确处理 204；
- Project canvas 通过 relationship Adapter 工作；
- Runs 页通过 Task / TaskAttempt 工作；
- Project usage 展示使用新字段，不读 `session_count`；
- MSW 对旧 paths 无 handler；
- generated contract 与 handwritten view model 之间只通过 feature Adapter 连接。

### 8.3 人工集成验收

删除前和删除后各执行一次：

1. 打开 Task 列表，按 Project 筛选；
2. 创建 Task 并确认选中和详情；
3. 发送后续输入，观察 messages / output / stream；
4. Retry，确认 Task ID 不变且新执行记录可见；
5. Fork，确认新 Task 身份与关系；
6. Move，确认 Project 和 Context 选择；
7. Archive / Unarchive；
8. Project canvas 新建和删除 relationship；
9. Project usage summary 数据显示；
10. Runs 页列表、Task 详情和执行历史；
11. 被删除的旧 API 全部 404；
12. 检查 API / Web 日志与 HTTP telemetry，确认无异常。

## 9. 验收命令

实施期间先运行定向测试，最终至少运行：

```bash
git diff --check
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src tests scripts
UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src tests scripts
UV_CACHE_DIR=/tmp/uv-cache uv run ty check
npm --prefix frontend run check:transport
npm --prefix frontend run lint
npm --prefix frontend run test:run
npm --prefix frontend run build
npm --prefix docs-site run build
bash scripts/ci.sh l0
bash scripts/ci.sh l1
```

不得使用无界 `-n auto`。若 sandbox 导致进程 / 线程测试假挂起，应在获批的正常主机环境运行标准 L1，不得以跳过或无界重试代替。

## 10. Commit 与 PR 分片

建议保持以下逻辑分片：

1. `feat: establish canonical task and project run contracts`
2. `refactor: migrate UI from session and project task compatibility APIs`
3. `refactor: remove session and task compatibility surfaces`
4. `docs: close task and session compatibility migration`

第 3 个 commit 只能在 Gate A 通过后产生。根级治理文档如果没有真实 drift 不应修改；`PROJECT_BASIS.md` 永远不由 Agent 修改。

## 11. 完成定义

只有同时满足以下条件，本 spec 才能标记 implemented 并归档：

- `/api/tasks` 是唯一 Task HTTP Interface；
- Project Task list 通过 Task filter 完成；
- Project relationship 和 usage 只存在于正式 domain Interface；
- WebUI 和 MSW 对旧 HTTP Interface 零调用；
- Session compatibility router、Module、schema、client 和测试全部删除；
- Task flat response、`new_task`、create `environment_id`、retry `task_input`、`/project` alias 和 permanent-delete 伪入口全部删除；
- frontend 不再手写重复 transport schema；
- generated transport 可确定性重建；
- Gate A 和 Gate B 证据完整；
- 删除后 release staging 人工验收通过；
- 长期架构文档和 active spec inventory 已反映新契约；
- compatibility inventory 不再把已删除的 Session / Task 格式列为保留项；
- production 环境未被操作。
