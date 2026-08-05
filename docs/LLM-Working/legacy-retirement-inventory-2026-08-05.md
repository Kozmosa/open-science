---
aliases:
  - Issue 76 legacy retirement inventory
tags:
  - openscience
  - migration
  - cleanup
issue: 76
date: 2026-08-05
---

# Issue #76 legacy retirement inventory

本文是 Issue #76 的 caller inventory 和生产检查点记录。它不是实现计划；实现完成后保留作为可审计的删除边界。此次检查只针对仓库文件和测试 fixture，未访问生产容器、数据库、端口、日志或数据。

## 当前 schema baseline

Fresh install 直接执行 `src/ainrf/db/migrations/current.py` 注册的 SQL baseline：

| Database | Baseline |
| --- | ---: |
| `agentic_researcher` | 33 |
| `auth` | 7 |
| `literature` | 7 |
| `terminal` | 1 |

正常 service startup 只知道这些 current baseline。历史 `agentic_researcher` version 32 到 33 的退休动作只在 `openscience migration retire-legacy preflight|apply|verify` 中存在；它不是 product import graph，也不是任意历史版本的永久升级链。

## Caller inventory

### 已删除

| Surface | 删除项 | 仓库证据 |
| --- | --- | --- |
| Historical migration/import | `db/migrations/{agentic_researcher,auth,literature,sessions,terminal}.py` 的长期 importer chain；`domain_migration/{conversation_v3,importer,reconciliation,sources}.py` | `db/migrations/current.py` 是唯一 startup registry；旧模块无静态、动态或字符串 caller |
| Cutover/control | `domain_control/cutover.py`、`legacy_source_guard.py`；cutover/reconciliation/importer 专属测试和 fixture | current writer 只检查当前 Conversation authority；旧 CLI/HTTP write path 已无入口 |
| Legacy Task runtime | `domain/{attempts,attempt_projection,tasks,worker,dispatch_wakeup}.py` 及专属 tests | `/api/tasks`、`domain-worker`、fixture worker 均使用 Conversation Task/Turn/Item/Submission/RuntimeExecution；`DispatchWakeup` 无 caller |
| HTTP/Pydantic | Attempt、RuntimeSession、Dispatch projection schemas/routes、`task_attempts` capability | generated transport 由当前 OpenAPI 重新生成；无 frontend operation 或 mock caller |
| Frontend/mock | `task_attempts` capability/type/mock/test 字段；Candidate `source_attempt_id` | MSW、feature type、generated schema 与 current Candidate provenance 一致 |
| Engine fallback | `ExecutionContext.prior_messages` 及三个 engine 的 `task_outputs` context-reconstruction fallback 和专属 tests | 全仓 caller 扫描显示没有生产构造点；Conversation runtime 以 canonical Turn/Item/Context snapshot 为 authority |
| Perf tooling | `task_outputs`、`task_harness_*`、`task_sessions`、`task_attempts` analyzer queries | `scripts/perf/run-all.py` 仍调用 analyzer，但 analyzer 现在只查询 current tables |

### 保留

| Surface | 保留项 | 边界 |
| --- | --- | --- |
| Current runtime | `domain/conversation_service.py`、`conversation_worker.py`、Conversation repositories/projection、Harness adapters | 当前 Task/Turn/Item/Submission/RuntimeExecution authority；不读取或写入旧 Attempt/RuntimeSession 表 |
| One-time migration | `db/retire_legacy.py` 与 `migration retire-legacy` | 只处理已确认的 version 32 状态；需要 maintenance、无 active runtime、已 committed cutover evidence；不得自动运行于 startup |
| Fresh install | `db/migrations/current.py`、`db/baselines/*.sql` | current schema baseline；不包含旧 migration chain |
| Admin audit | `domain_migration/audit.py`、`/api/admin/domain/legacy-records`、`domain-migration records|record` | 只读、脱敏、只保留 `legacy_domain_records` 历史证据；不把历史 payload 转成可写 Task |
| Maintenance/restore | `DomainMaintenanceService`、`BackupService`、post-restore schema validation | 负责 preflight、备份/恢复和人工 rollback 边界；不执行生产操作 |
| Runtime identity | `runtime_launch_key`、checkpoint identity 和 current RuntimeExecution | 这是当前 engine execution identity，不是已删除的 Attempt repository；不能以静态字符串扫描误删 |
| Parallel slices | #71 的 `domain/worker.py` conversation-only initialization；#75 的 telemetry、backup、domain service、overview jobs changes | 本 PR 记录 overlap；最终按依赖分支验证，不复制其普通重构 |

### 分类结论

- 长期能力：Conversation domain、current Harness runtime、maintenance、backup/restore、admin read-only audit、`openscience`/`ainrf` CLI 和正式 HTTP/generated transport。
- 下一次 Migration：唯一的 `version 32 -> 33` `retire-legacy` 操作；它只负责在人工维护窗口中删除已完成的旧 runtime/cutover 表并重建 Candidate provenance 表。
- Admin audit：`legacy_domain_records` 和两个只读 admin endpoints；这是历史取证，不是 product fallback。
- 已完成待退休：旧 migration chain、cutover fuse/source guard、Attempt/RuntimeSession repository/projection/worker、旧 task output history fallback、相关指标/fixture/mock/专属测试。
- 无 caller：被删除的 importer/reconciliation/source modules、旧 control CLI、旧 Attempt API projection、旧 analyzer queries。静态/动态/字符串入口扫描没有发现仓库 caller。

## 生产 pre-merge checklist（用户控制）

以下步骤必须由用户在生产维护窗口完成；本 PR 不执行这些步骤，也不将其结果假设为已完成：

1. 生成并验证完整 production backup，并在隔离 staged root 完成 restore/integrity/post-restore validation。
2. 确认 release manifest、backend/frontend/worker artifact SHA 一致；停止 writers，进入 maintenance，并确认 participant drain、active Turn/Submission 和 tenant/workspace source 稳定。
3. 在生产 state root 运行 `openscience migration retire-legacy preflight`，人工核对报告为 ready；不满足条件时停止。
4. 运行一次 `openscience migration retire-legacy apply`，随后运行 `openscience migration retire-legacy verify`；保存 JSON 报告和 schema/integrity evidence。
5. 启动同一 release manifest，执行只读 health、domain/API、Task/Turn/Item、admin audit 和 backup restore post-smoke；确认没有旧表访问或 legacy writer。
6. 失败时停止 writers，保留现场 evidence，使用已验证的上一份 release manifest 和完整 backup 人工 rollback；不要尝试从旧表恢复一个新的双写 compatibility path。

Rollback 风险：该操作删除旧 runtime/cutover tables，不能靠代码 rollback 恢复已经删除的数据。必须先完成 backup + isolated restore；代码版本回滚与数据恢复是两个独立动作。任何未提供完整 evidence 的生产状态都应保持 fail-closed，不得声称 migration 已完成。

## 重叠文件与依赖

- #71：`src/ainrf/domain/worker.py` 的 conversation-only initialization。#76 的 retirement 删除旧 wrapper/legacy worker caller；普通 initialization 不在本 PR 中重构。最终 PR 依赖 #71 最新 head，并写明 `Depends on #71`。
- #75：`src/ainrf/domain_telemetry.py`、`src/ainrf/backup/service.py`、`src/ainrf/domain/service.py`、`src/ainrf/domain/overview_jobs.py`。#76 只做与旧 authority retirement 直接相关的 caller 收口；#75 的控制面深度化和 telemetry 清理保持其 owner 边界。

## 验证命令

最终交付前运行并记录：

```text
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest <migration/current-schema/retirement/backup/production-contract lanes>
UV_CACHE_DIR=/tmp/uv-cache uv run --offline ruff check src tests scripts
UV_CACHE_DIR=/tmp/uv-cache uv run --offline python -m compileall -q src/ainrf tests
npm --prefix frontend run check:transport
npm --prefix frontend run build
bash scripts/ci.sh l1
```

静态扫描同时检查 `import`/lazy import、`importlib`/字符串入口、CLI/HTTP/generated transport/frontend/test/deployment/docs caller；扫描中的历史名称只允许出现在本 inventory、retirement SQL/verification 和 archived specs 中。
