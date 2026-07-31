---
title: 架构与兼容契约
description: OpenScience 当前架构、HTTP contract、generated transport、release/rollback 边界与兼容债务清单。
---

# 架构与兼容契约

本文是 OpenScience 当前架构与 compatibility surface 的长期 owner。活跃设计保留在 `docs/superpowers/specs/`，已完成或被取代的设计保留在 `docs/superpowers/specs/archived/`；当前产品 contract 以代码、generated OpenAPI artifact、正常测试和本文为准。

## 品牌与工程身份

- **OpenScience** 是产品与用户可见品牌，用于 WebUI、公开文档、CLI help 和发布物料。
- `AINRF` / `ainrf` 是稳定内部工程身份，用于 Python package/import namespace、状态路径、Linux identity、部署资源和 Prometheus metric namespace。
- `osci` 只用于前端设计系统、CSS 命名空间或紧凑品牌展示，不建立第三套后端 package、状态目录或部署身份。
- 用户文档优先使用 `openscience` CLI 与 `OPENSCIENCE_*`；`ainrf` CLI 与 `AINRF_*` 保持支持。它们不是等待一次性全量删除的 compatibility debt。

## 当前架构

```mermaid
flowchart TD
    UI["React WebUI<br/>app composition"] --> Feature["feature adapters<br/>and view models"]
    Feature --> Client["shared HTTP client<br/>/api"]
    Client --> Transport["FastAPI transport<br/>routes and schemas"]
    Transport --> Modules["narrow domain Modules<br/>committed v2 authority"]
    Modules --> Runtime["runtime and harness adapters"]
    Modules --> SQLite["authoritative SQLite state"]
    Schema["FastAPI OpenAPI"] --> Generated["generated transport<br/>types and operation metadata"]
    Generated --> Feature
    Generated --> Mock["MSW transport adapter"]
```

- Backend product graph 不允许 cycle，也不允许 non-API product code 反向依赖 `ainrf.api`。
- Project、Workspace、Environment、Task 等领域通过窄 application Interface 暴露能力；SQLite repository 与共享 write kernel 保持私有。
- Release E 已完成 committed-v2 authority cutover。产品路径不得重新引入 legacy writer、legacy read fallback、双读或双写。
- Frontend 依赖方向为 `app -> features -> shared/design-system`。`shared` 与 `design-system` 不依赖 feature，page 只负责 composition。
- UI 不直接消费 raw generated payload；feature adapter 将 transport type 映射为 view model。

## HTTP 与 generated transport

- Canonical HTTP prefix 是 `/api`。
- 产品 router 只注册在 `/api`。root 与产品 `/v1` aliases 已在用户确认当前无外部调用者后删除；`/v1/models`、`/v1/messages` 继续作为独立外部协议保留。
- FastAPI/Pydantic OpenAPI 是唯一 transport schema authority。
- `/api/tasks` 是唯一正式 Task HTTP Interface；Project-owned relationship 与 usage 投影位于 `/api/domain/projects/{project_id}/task-relationships` 和 `/usage-summary`。管理侧 `/runs` 直接读取 Task 与 TaskAttempt，不存在独立 Session 资源。
- `npm --prefix frontend run generate:transport` 确定性生成 `frontend/src/generated/transport/`。
- `npm --prefix frontend run check:transport` 重建并检查 schema manifest、operation/path metadata 与工作树 drift。
- Generated transport 的长期验证由正常 drift gate、真实 HTTP contract tests 和 MSW Adapter tests 负责；临时 architecture-cleanup suite 已在 P6 删除。

## Release 与 rollback contract

- L0 是有界开发内循环；L1 是不依赖 Docker 或外部服务的完整确定性 gate。
- 默认 production 模型是实验室内部的计划维护窗口，允许约 2–3 小时停机，不要求零停机切换或任意中断后的自动接管恢复。
- Frontend、backend 与 worker 必须来自同一份简单 release manifest，并通过 build info、contract version 和 release smoke 验证版本一致；不要求高保证供应链证明或逐步骤发布 ledger。
- 领域结构重构保持 durable schema 与 canonical HTTP behavior 不变，可以回滚代码 artifact。
- Compatibility surface 的 removal change 必须同时更新 schema、generated artifact、contract tests、文档和 rollback 验证记录。
- L4 采用人工维护窗口流程：发布前完成完整备份及隔离恢复验证，停止 writer 后执行必要迁移，启动同版本服务并执行只读 post-smoke；失败时按 runbook 人工恢复数据和上一份 release manifest。

## 环境与发布边界

- Local development 不启动 Docker，使用 `uv`、npm 和 `scripts/dev.sh` 运行 repo 外隔离状态；未来 Pixi 只能补充工具链，不能削弱数据隔离。
- Staging 默认是 development-oriented 容器环境，允许源码和 staging 专属前端产物 bind mount，用于快速联调，不作为不可变 release evidence。
- Production 只消费同一 release manifest 绑定的不可变镜像。WebUI、nginx 配置、API 和 worker 代码均在镜像中；只允许注入 secrets、运行配置与 named persistent volumes，不依赖 Git checkout 或 worktree。
- API、domain worker 与 literature worker 必须使用同一个 API image reference。Web、API 与监控镜像全部构建成功后才能更新运行服务，禁止独立发布前端或后端。
- 默认发布不要求独立 release staging。若未来接入 registry 或确有额外验收需求，可以对同一组镜像引用增加 staging 验收，但不能把它扩张为默认的复杂发布控制面。代码 rollback 以上一份完整 manifest 为单位，数据 rollback 使用发布前验证过的完整备份。

## Fail-closed compatibility inventory

用户已用“当前没有外部调用者”的人工判断覆盖原观察窗口门槛。资源兼容入口、Session / Task compatibility projections 与 Literature `/convert` 已在 caller、generated transport 和 immutable release staging 验收后删除。下表是当前长期支持或仍承担只读迁移/审计职责的完整清单。

| Surface | Owner | 保留理由 | 状态 |
| --- | --- | --- | --- |
| `openscience` CLI | Product CLI | 用户可见的正式产品入口 | 长期支持 |
| `ainrf` CLI | Backend runtime | 稳定内部工程与运维入口 | 长期支持 |
| `AINRF_*` backend config | Backend runtime | canonical 后端配置命名空间 | 长期支持 |
| 对应的 `OPENSCIENCE_*` backend config aliases | Product / release | `PROJECT_BASIS.md` 明确规定的正式兼容别名 | 长期支持，不是 cleanup debt |
| `/v1/models`、`/v1/messages` | External protocol adapter | Anthropic-compatible 外部协议入口 | 长期支持 |
| `domain-migration` CLI 与 `/api/admin/domain/legacy-records` | Domain migration / release | committed-v2 之前状态的只读迁移、reconciliation 与审计证据；不得成为 product read fallback | 保留，migration/admin-only |

后续 removal 默认仍要求 caller 迁移和同步更新 schema、contract tests、文档与 rollback evidence；是否再次由人工判断覆盖观察窗口，需要由用户逐批明确确认。

临时 `ainrf_cleanup_*` registry、指标、持久化表、日志和 Dashboard，以及 superseded `ainrf_deprecated_*` 指标、旧统计 helper 与 Release E 告警已在架构清理最终收口中删除。Compatibility route 观察统一由长期、低基数的 `ainrf_http_contract_*` 指标和 durable aggregate 承担；正式长期 alias 不再产生 cleanup-only 遥测。

## 长期验证 owner

- Backend Module 与 HTTP contract：`tests/` 和 `bash scripts/test.sh <lane>`。
- Generated transport drift：`npm --prefix frontend run check:transport`。
- Frontend feature 与 MSW Adapter：`npm --prefix frontend run test:run`。
- Repository deterministic gate：`bash scripts/ci.sh l0` 与 `bash scripts/ci.sh l1`。
- 发布、rollback 与生产 compatibility telemetry：release owner；没有完整窗口证据时必须 fail-closed 保留。
