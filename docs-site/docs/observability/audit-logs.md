---
title: 审计日志
description: OpenScience 审计日志架构、事件目录与日志查询方法。
---

OpenScience 通过 `structlog` 输出显式接线的结构化安全审计事件。每个事件包含 `event`、`severity`、`timestamp` 和 `component`（固定为 `audit`）；HTTP 请求内产生的事件还会携带 `request_id`。常规请求日志只记录 method、稳定 route template、status 与耗时，不序列化 Authorization/Cookie、query string 或请求体。审计 producer 只提交有界 ID、分类字段和文件 basename，不依赖一个可以安全接收任意敏感 payload 的“全局自动脱敏”承诺。

## 终端事件

| 事件 | 级别 | 字段 |
|------|------|------|
| `terminal.session.created` | info | session_id, environment_id, user_id |
| `terminal.session.reset` | info | session_id, environment_id, user_id |
| `terminal.websocket.opened` | info | session_id, environment_id, user_id, attachment_id |
| `terminal.websocket.closed` | info | session_id, environment_id, user_id, attachment_id |

## 文件事件

| 事件 | 级别 | 字段 |
|------|------|------|
| `files.sensitive_path_access` | high | path (basename), pattern, user_id, environment_id |

## Durable domain audit

Domain Module 会把受审计的 Project、Environment、Workspace、Task 与 Conversation mutation 在同一 SQLite 事务中写入 `domain_audit_events` durable ledger。它与本页的 `component=audit` structlog 流不是同一个 Interface：不能通过 grep backend log 来证明或否定 domain mutation audit。认证成功/失败目前由 `ainrf_auth_login_*_total` 观测，锁定状态由 Auth Module 的持久化登录尝试记录管理；它们也不属于本页事件目录。

## 日志查询示例

```bash
# 敏感文件访问
grep '"event":"files.sensitive_path_access"' logs/backend-*.log

# 终端会话
grep '"event":"terminal.' logs/backend-*.log

# 所有 high/critical 级别事件
grep '"severity":"high\|"severity":"critical"' logs/backend-*.log
```

HTTP 请求内的事件可通过 `request_id` 与同一次请求的结构化日志关联。Terminal WebSocket 事件使用 `attachment_id`、`session_id`、`environment_id` 与 `user_id` 关联连接生命周期。

## 相关文档

- [可观测性概览](/observability/) — 架构概览与请求 ID 关联
- [Prometheus 指标](/observability/metrics) — 指标参考
- [安全事件响应](/security/checklist) — 安全事件排查流程
