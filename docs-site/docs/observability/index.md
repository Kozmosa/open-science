---
title: 可观测性概览
description: OpenScience 审计日志架构、审计事件目录与请求 ID 关联机制。
---

OpenScience 提供完整的可观测性能力：结构化审计日志、Prometheus 指标、Grafana 监控栈和 Gatus uptime 状态页。

| 文档 | 说明 |
| --- | --- |
| [审计日志](/observability/audit-logs) | structlog JSON 审计事件、事件目录与日志格式。 |
| [Prometheus 指标](/observability/metrics) | 计数器、直方图、仪表盘指标参考与 PromQL 查询。 |
| [监控栈](/observability/monitoring-stack) | Prometheus、Grafana 与 Gatus 部署架构、Dashboard、主动探测与告警规则。 |

## 审计日志架构

OpenScience 通过 `structlog` 输出显式接线的结构化 JSON 安全审计事件。每个事件包含：

| 字段 | 说明 |
|------|------|
| `event` | 事件名（如 `terminal.session.created`） |
| `severity` | `info`、`warning`、`high` 或 `critical` |
| `timestamp` | ISO 8601 UTC |
| `component` | 固定为 `audit` |
| `request_id` | HTTP 请求内事件的关联 UUID |
| 附加上下文 | user_id、client_ip 等 |

常规请求日志只记录 method、稳定 route template、status 与耗时，不序列化 Authorization/Cookie、query string 或请求体。审计 producer 只提交有界 ID、分类字段和文件 basename；不要把任意含凭据 payload 交给日志系统。

## 审计事件目录

### 终端事件

| 事件 | 级别 | 字段 |
|------|------|------|
| `terminal.session.created` | info | session_id, environment_id, user_id |
| `terminal.session.reset` | info | session_id, environment_id, user_id |
| `terminal.websocket.opened` | info | session_id, environment_id, user_id, attachment_id |
| `terminal.websocket.closed` | info | session_id, environment_id, user_id, attachment_id |

### 文件事件

| 事件 | 级别 | 字段 |
|------|------|------|
| `files.sensitive_path_access` | high | path (basename), pattern, user_id, environment_id |

### Durable domain audit

Domain Module 将受审计的 Project、Environment、Workspace、Task 与 Conversation mutation 在同一 SQLite 事务中写入 `domain_audit_events` durable ledger；它不是 `component=audit` structlog 流。认证成功/失败由 `ainrf_auth_login_*_total` 观测，锁定状态由 Auth Module 的持久化登录尝试记录管理；它们也不属于本页 structlog 事件目录。

## 日志文件格式

日志写入 `<state_root>/logs/backend-YYYYMMDD.log`，每行一个 JSON 对象：

```json
{
  "event": "terminal.session.created",
  "severity": "info",
  "component": "audit",
  "user_id": "alice",
  "environment_id": "env-example",
  "session_id": "session-example",
  "client_ip": "10.0.0.1",
  "request_id": "a1b2c3d4-...",
  "timestamp": "2026-06-04T12:00:00Z"
}
```

## 请求 ID 关联

每个 HTTP 请求通过 `X-Request-ID` 响应头获得一个 UUID4 `request_id`。该 ID 绑定到 `structlog` 上下文变量，同一次 HTTP 请求内的日志行可据此关联。Terminal WebSocket 生命周期使用 `attachment_id`、`session_id`、`environment_id` 与 `user_id` 关联。

## 相关文档

- [审计日志](/observability/audit-logs) — 事件详情
- [Prometheus 指标](/observability/metrics) — 指标参考
- [安全架构](/security/) — 安全配置
