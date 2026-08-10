---
aliases:
  - Literature HTTP Interface
tags:
  - openscience
  - literature
  - transport
doc_state: current
---

# Literature transport contract

本文记录 `/api/literature` 当前 HTTP Interface inventory。FastAPI/Pydantic OpenAPI 是 schema authority；application result 由 Literature tracking / task saga Module 产生，HTTP presenter Adapter 在 transport Seam 白名单映射；SQLite row 不属于 HTTP Interface。

## 正式 Interface（19 operations）

| Method | Path | Auth | Request | Success | Error | Caller | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/overview` | 当前用户 | 无 | `LiteratureOverviewResponse` | 401/500 | Literature page | overview |
| GET | `/topics` | 当前用户 | query | `LiteratureTopicListResponse` | 401/422 | Literature page/MSW | topic |
| POST | `/topics` | 当前用户 | `LiteratureTopicRequest` | `LiteratureTopicResponse` | 401/422 | Literature page/MSW | topic |
| GET | `/topics/{topic_id}` | 当前用户 | path | `LiteratureTopicResponse` | 401/404/422 | generated Interface/MSW | topic |
| PATCH | `/topics/{topic_id}` | 当前用户 | `LiteratureTopicUpdateRequest` | `LiteratureTopicResponse` | 401/404/422 | Literature page/MSW | topic |
| DELETE | `/topics/{topic_id}` | 当前用户 | path | 204 | 401/404/422 | Literature page/MSW | topic |
| POST | `/topics/preview` | 当前用户 | `LiteratureTopicRequest` | `LiteratureTopicPreviewResponse` | 401/422 | Literature page/MSW | topic |
| POST | `/checks` | 当前用户 + Idempotency-Key | `LiteratureCheckRequest` | `LiteratureCheckResponse` | 401/409/422 | Literature page/MSW | check |
| GET | `/checks/current` | 当前用户 | 无 | `LiteratureCheckResponse | null` | 401 | Literature page | check |
| GET | `/checks` | 当前用户 | limit | `LiteratureCheckListResponse` | 401/422 | Literature page/MSW | check |
| GET | `/checks/{check_id}` | 当前用户 | path | `LiteratureCheckResponse` | 401/404/422 | Literature page/MSW | check |
| GET | `/papers` | 当前用户 | view/topic/category/summary/task/cursor/limit | `LiteraturePaperListResponse` | 401/422 | Literature page/MSW | paper |
| GET | `/papers/{paper_id}` | 当前用户 | path | `LiteraturePaperDetailResponse` | 401/404/422 | Literature page/MSW | paper |
| GET | `/papers/{paper_id}/versions` | 当前用户 | path | `LiteraturePaperVersionListResponse` | 401/404/422 | generated Interface/MSW | paper version |
| PATCH | `/papers/{paper_id}/state` | 当前用户 + Idempotency-Key | `LiteraturePaperStateRequest` | `LiteraturePaperDetailResponse` | 401/404/409/422 | Literature page/MSW | paper state |
| GET | `/papers/{paper_id}/summary` | 当前用户 | path | `LiteratureSummaryResponse` | 401/404/422 | Literature page/MSW | summary |
| POST | `/papers/{paper_id}/summary` | 当前用户 + Idempotency-Key | `LiteratureSummaryRequest` | `LiteratureSummaryResponse` | 401/404/409/422 | Literature page/MSW | summary |
| POST | `/papers/{paper_id}/research-task` | 当前用户 + Idempotency-Key | `LiteratureResearchTaskRequest` | `LiteratureResearchTaskResponse` | 401/403/404/409/422/503 | Literature page/MSW | research-task saga |
| GET | `/papers/{paper_id}/research-tasks` | 当前用户 | path | `LiteratureResearchTaskListResponse` | 401/403/404/422/503 | Literature page/MSW | research-task saga |

所有列表使用 `{items,total,next_cursor}`。Summary status 包含 `stale`。paper list 支持 `summary_status` 与 `has_research_task`。singular research-task 查询不属于 accepted Interface，WebUI 已改用正式列表恢复幂等 intent。

## Compatibility Interface（7 operations）

| Method | Path | 正式 Adapter target | Repo caller audit | 状态 |
| --- | --- | --- | --- | --- |
| GET | `/subscriptions` | topic list | 无 WebUI/script caller | 保留，待批准 |
| POST | `/subscriptions` | topic create | 无 WebUI/script caller | 保留，待批准 |
| PUT | `/subscriptions/{subscription_id}` | topic update | 无 WebUI/script caller | 保留，待批准 |
| DELETE | `/subscriptions/{subscription_id}` | topic delete | 无 WebUI/script caller | 保留，待批准 |
| GET | `/subscriptions/{subscription_id}/fetch-status` | durable check list | 无 WebUI/script caller | 保留，待批准 |
| POST | `/subscriptions/{subscription_id}/fetch` | durable check create | 无 WebUI/script caller | 保留，待批准 |
| POST | `/papers/{paper_id}/read` | paper state update | 无 WebUI/script caller | 保留，待批准 |

这些 routes 直接把 canonical `topic_id` 呈现为兼容 transport 的 `subscription_id`，不再依赖旧 service、双写方法或持久化映射列。自动门禁固定 inventory、验证 repo caller absence，并确保 generated transport 仍准确反映保留状态。删除仍需隔离完整手动验收和用户逐批批准；本次未删除，也未操作 production 或为 telemetry 部署未验收代码。
