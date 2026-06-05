---
title: Observability
---

# Observability

## Audit Logging Architecture

AINRF produces structured JSON audit events via `structlog`. Every event includes:

- `event` — event name (e.g., `auth.login.success`)
- `severity` — `info`, `warning`, `high`, or `critical`
- `timestamp` — ISO 8601 UTC
- `component` — always `audit`
- `request_id` — UUID linking all events in one request
- Additional context fields (user_id, client_ip, etc.)

All sensitive values (tokens, passwords, API keys) are automatically redacted.

## Audit Event Catalog

### Authentication Events

| Event | Severity | Fields |
|---|---|---|
| `auth.login.success` | info | user_id, client_ip |
| `auth.login.failed` | warning | user_id, client_ip, reason |
| `auth.register.submitted` | info | user_id |
| `auth.refresh.failed` | warning | reason |

### Terminal Events

| Event | Severity | Fields |
|---|---|---|
| `terminal.session.created` | info | session_id, environment_id, user_id |
| `terminal.session.reset` | info | session_id |
| `terminal.websocket.opened` | info | session_id |
| `terminal.websocket.closed` | info | session_id |

### Code-Server Events

| Event | Severity | Fields |
|---|---|---|
| `code.session.created` | info | user_id, environment_id |
| `code.session.stopped` | info | user_id |
| `code.proxy.request` | info | — |

### File Events

| Event | Severity | Fields |
|---|---|---|
| `files.read` | info | path (basename), user_id |
| `files.upload` | info | filename, user_id |
| `files.sensitive_path_access` | high | path (basename), pattern, user_id |

### Environment Events

| Event | Severity | Fields |
|---|---|---|
| `environment.created` | info | environment_id, user_id |
| `environment.updated` | info | environment_id, user_id |
| `environment.ssh_field_changed` | warning | environment_id, user_id |
| `environment.code_server_install_requested` | info | environment_id |

### Task Events

| Event | Severity | Fields |
|---|---|---|
| `task.created` | info | task_id, user_id |
| `task.deleted` | info | task_id, user_id |
| `task.permanent_deleted` | warning | task_id, user_id |

## Prometheus Metrics Reference

Enable with `AINRF_METRICS_ENABLED=true`. Endpoint: `GET /metrics`

### Counters

| Metric | Labels | Description |
|---|---|---|
| `ainrf_http_requests_total` | method, path, status | Total HTTP requests |
| `ainrf_auth_login_success_total` | — | Successful logins |
| `ainrf_auth_login_failed_total` | reason | Failed logins by reason |
| `ainrf_terminal_exec_total` | environment_id | Terminal exec commands |
| `ainrf_terminal_exec_denied_total` | — | Denied terminal exec |
| `ainrf_code_session_created_total` | — | Code-server sessions |
| `ainrf_files_sensitive_path_access_total` | pattern | Sensitive file access |
| `ainrf_environment_update_total` | — | Environment updates |

### Histograms

| Metric | Description |
|---|---|
| `ainrf_http_request_duration_seconds` | Request latency distribution |

### Gauges

| Metric | Description |
|---|---|
| `ainrf_terminal_ws_active` | Active terminal WebSocket connections |

## Log File Format

Logs are written to `<state_root>/logs/backend-YYYYMMDD.log`, one JSON object per line:

```json
{"event":"auth.login.success","severity":"info","component":"audit","user_id":"alice","client_ip":"10.0.0.1","request_id":"a1b2c3d4-...","timestamp":"2026-06-04T12:00:00Z"}
```

## Request ID Correlation

Every HTTP request receives a UUID4 `request_id` via the `X-Request-ID` response header. This ID is bound to `structlog` context variables, so all log lines within that request (including audit events) carry the same `request_id`. WebSocket connections inherit the request_id from their upgrade request.

## Example Prometheus Queries

```promql
# Login failure rate (per second, 5-min window)
rate(ainrf_auth_login_failed_total[5m])

# 99th percentile request latency
histogram_quantile(0.99, rate(ainrf_http_request_duration_seconds_bucket[5m]))

# Active terminal sessions
ainrf_terminal_ws_active

# Sensitive file access by pattern
sum by (pattern) (rate(ainrf_files_sensitive_path_access_total[1h]))
```

## Grafana Dashboard Panels

Recommended panels:

1. **Login Activity** — Stacked graph of `ainrf_auth_login_success_total` vs `ainrf_auth_login_failed_total`
2. **Request Latency** — Heatmap of `ainrf_http_request_duration_seconds`
3. **Terminal Sessions** — Stat panel of `ainrf_terminal_ws_active`
4. **Security Events** — Table of `ainrf_files_sensitive_path_access_total` by pattern
5. **Environment Changes** — Counter of `ainrf_environment_update_total`

## Alert Recommendations

See `deploy/examples/prometheus-rules.example.yml` for starting-point alert rules. Key alerts:

- High login failure rate → possible brute-force
- Sensitive file access → investigate user intent
- Terminal exec denials → policy violations
- High error rate → backend issues
