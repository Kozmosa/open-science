# Prometheus Metrics Reference

A complete catalog of every Prometheus metric exposed by AINRF at the `GET /metrics` endpoint. Metrics are grouped by subsystem; each entry documents the metric type, label dimensions, emission trigger (call site), and typical use in dashboards and alerts.

Throughout this reference, Counter metrics are cumulative and strictly increasing over the process lifetime; Histogram metrics auto-generate `_bucket`, `_sum`, and `_count` suffixes; Gauge metrics are freely settable absolute values.

---

## HTTP Layer

Metrics emitted by the `build_http_metrics_middleware` (every HTTP request except `/metrics` itself).

| Metric | Type | Labels | Emitted When |
|--------|------|--------|--------------|
| `ainrf_http_requests_total` | Counter | `method` (GET/POST/…), `path` (normalized, UUIDs/numbers replaced with `{id}`), `status` (string) | Every HTTP request, including errors |
| `ainrf_http_request_duration_seconds` | Histogram | `method`, `path` (same normalization) | Every HTTP request |

**Default histogram buckets**: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s.

**Derived PromQL**:
- Error rate: `rate(ainrf_http_requests_total{status=~"5.."}[5m]) / rate(ainrf_http_requests_total[5m])`
- P95 latency: `histogram_quantile(0.95, rate(ainrf_http_request_duration_seconds_bucket[5m]))`

---

## Authentication

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_auth_login_success_total` | Counter | _(none)_ | User successfully authenticates | `routes/auth.py` |
| `ainrf_auth_login_failed_total` | Counter | `reason` (`invalid_credentials` / `locked`) | Login attempt fails | `routes/auth.py` |

---

## SSH & Remote Execution

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_ssh_connection_attempt_total` | Counter | `host` | An SSH connection is opened | `execution/ssh.py` |
| `ainrf_ssh_connection_error_total` | Counter | `host`, `error_type` | An SSH connection or command fails | `execution/ssh.py` |
| `ainrf_ssh_command_duration_seconds` | Histogram | `host` | An SSH command completes (success or failure) | `execution/ssh.py` |

---

## Terminal

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_terminal_exec_total` | Counter | _(none)_ | A command is executed in a terminal session | `routes/terminal.py` |
| `ainrf_terminal_exec_denied_total` | Counter | _(none)_ | A command execution is denied by policy | `routes/terminal.py` |
| `ainrf_terminal_ws_active` | Gauge | _(none)_ | WebSocket terminal session opens (+1) / closes (−1) | `routes/terminal.py` |

> **Dashboard tip**: Plot `ainrf_terminal_ws_active` as a time-series to see concurrent terminal session count.

---

## Database

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_db_query_duration_seconds` | Histogram | `db` (SQLite connection path stem, e.g. `literature`, `auth`) | Any SQLite query completes | `db/instrumentation.py` |
| `ainrf_db_slow_query_total` | Counter | `db` | A SQLite query exceeds 1 second | `db/instrumentation.py` |

---

## Files & Security

| Metric | Type | Labels | Emitted When |
|--------|------|--------|--------------|
| `ainrf_files_sensitive_path_access_total` | Counter | `pattern` (bounded sensitive-path category) | An authorized file route attempts to access a sensitive path (e.g. `.env` or `*.pem`) |

---

## Environments

| Metric | Type | Labels | Emitted When |
|--------|------|--------|--------------|
| `ainrf_environment_update_total` | Counter | _(none)_ | An environment detection or configuration update occurs |
| `ainrf_code_session_created_total` | Counter | _(none)_ | A new code session (Claude Code / Codex process) is spawned |

---

## Client Telemetry

### Client-side error events

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_client_error_events_total` | Counter | _(none)_ | Frontend `ErrorBoundary` sends an error to `POST /api/client-logs` | `routes/client_logs.py` |

### Client-side web vitals

Ingested via `POST /api/client-metrics`. Each metric is created lazily as a Histogram with the `rating` label and a fixed name pattern `ainrf_client_<name>_seconds`.

| Metric | Type | Labels | Source | Good | Poor |
|--------|------|--------|--------|------|------|
| `ainrf_client_lcp_seconds` | Histogram | `rating` | `largest-contentful-paint` PerformanceObserver | ≤ 2.5s | > 4.0s |
| `ainrf_client_fcp_seconds` | Histogram | `rating` | `paint` PerformanceObserver (first-contentful-paint) | ≤ 1.8s | > 3.0s |
| `ainrf_client_inp_seconds` | Histogram | `rating` | `event` PerformanceObserver | ≤ 200ms | > 500ms |
| `ainrf_client_cls_seconds` | Histogram | `rating` | `layout-shift` PerformanceObserver | ≤ 0.1 | > 0.25 |

Rating values are `"good"`, `"needs-improvement"`, or `"poor"` per Google's Core Web Vitals thresholds.

---

## Literature Tracking (durable planner and worker)

The current Literature Module has removed the retired APScheduler fetch cluster and fixed per-subscription loop. `ConversationWorkerRuntime` invokes `run_planner_cycle()` for due checks; `LiteratureTrackingService` commits checks, source snapshots, paper versions, matching, user state, summaries, work items, and outbox records to SQLite. Dramatiq publishes and executes durable work IDs through `process_durable_work_item`, while `LiteratureTaskSagaService` coordinates current Task creation through the Conversation Domain. SQLite and durable domain telemetry are the authority; Redis/Dramatiq and process-local counters are transport or observation layers only.

### Current durable telemetry

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_domain_literature_saga_events_total` | Counter | `outcome` | A Literature-to-Task saga transition is durably recorded | `domain_telemetry.record_literature_saga_event()` |
| `ainrf_domain_literature_saga_intents` | Gauge | `status` | Current durable Literature-to-Task intent count is hydrated during a domain telemetry scrape | `domain_telemetry.refresh_domain_metrics()` |
| `ainrf_domain_literature_saga_oldest_pending_age_seconds` | Gauge | _(none)_ | Age of the oldest non-terminal Literature-to-Task intent during a durable scrape | `domain_telemetry.refresh_domain_metrics()` |
| `ainrf_literature_summarize_total` | Counter | `status` (`success` / `failed`) | A current Literature worker summary call completes or fails | `literature/summarizer.py` |
| `ainrf_literature_summarize_duration_seconds` | Histogram | _(none)_ | A current Literature worker summary call ends | `literature/summarizer.py` |

**Derived PromQL** (examples):

- Literature-to-Task saga completions:
  ```
  rate(ainrf_domain_literature_saga_events_total{outcome="completed"}[1h])
  ```
- Pending Literature-to-Task intents by recovery state:
  ```
  sum by (status) (ainrf_domain_literature_saga_intents)
  ```
- Summary success rate:
  ```
  rate(ainrf_literature_summarize_total{status="success"}[1h])
  / rate(ainrf_literature_summarize_total[1h])
  ```
- Oldest pending Literature-to-Task intent:
  ```
  ainrf_domain_literature_saga_oldest_pending_age_seconds
  ```

---

## Rate Limiting

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_rate_limited_total` | Counter | `reason`, `route` | A request is rejected by rate limiting middleware or a client-telemetry quota | `api/middleware`, `routes/client_logs.py`, `routes/client_metrics.py` |

The `route` label is bounded before recording: known static client telemetry
routes and FastAPI route templates are retained, while opaque or unmatched
paths are reported as `/unmatched`. This keeps public exposition free of
tenant/resource identifiers.

All histograms use the default buckets: 5ms, 10ms, 25ms, 50ms, 100ms,
250ms, 500ms, 1s, 2.5s, 5s, 10s.

---

## OpenTelemetry (Conditional)

When `AINRF_OTEL_ENABLED=true`, OpenTelemetry auto-instrumentation creates its own metrics (not documented here — see the OTel SDK documentation). The OTel metrics are exported to the configured OTLP endpoint and are **not** mixed into the Prometheus `/metrics` endpoint. Key auto-instrumented spans:

- `FastAPIInstrumentor` — all HTTP requests (excluding `/health`, `/metrics`)
- `SQLite3Instrumentor` — all database queries
- `HTTPXInstrumentor` — all outbound HTTP calls

---

## Enabling Metrics Exposition

The `/metrics` endpoint is gated by the `AINRF_METRICS_ENABLED` environment variable:

```bash
# docker-compose.yml (production)
AINRF_METRICS_ENABLED: "true"

# returns HTTP 404 when false
```

When enabled, the endpoint is available at `/metrics`, `/api/metrics`, and `/v1/metrics` (all three paths route to the same handler).

---

## Metric Naming Convention

All AINRF-specific metrics follow the `ainrf_<subsystem>_<metric_name>_<unit>` pattern:

| Convention | Example |
|------------|---------|
| Counter: `_total` suffix | `ainrf_auth_login_failed_total` |
| Histogram: `_seconds` suffix | `ainrf_http_request_duration_seconds` |
| Gauge: no mandatory suffix | `ainrf_terminal_ws_active` |
| Subsystem grouping | `ainrf_literature_*`, `ainrf_rate_limited_*`, `ainrf_ssh_*` |

Histogram bucket suffixes (`_bucket`, `_sum`, `_count`) are added automatically by `prometheus_client` and are not part of the declared metric name.

---

## Prometheus Alerting Rules

Alerting rules are at `deploy/config/prometheus/rules/ainrf-alerts.yml`. The bundled example at `deploy/examples/prometheus-rules.example.yml` provides a starter set (see Section 5 of the [archived observability stack design doc](../superpowers/specs/archived/2026-06-15-observability-stack-design.md) for the original 14-rule inventory).

---

## Related Documents

- [Observability Stack Architecture](../superpowers/specs/archived/2026-06-15-observability-stack-design.md) — archived design record for the three-layer observability system
- `src/ainrf/telemetry/metrics.py` — metric pre-declaration table, public mutation and reset API
- `src/ainrf/api/routes/metrics.py` — metrics exposition endpoint
- `src/ainrf/telemetry/rate_limit.py` — bounded rate-limit metric recording
- `src/ainrf/api/routes/client_metrics.py` — client-side web vitals ingestion endpoint
- `deploy/examples/prometheus-rules.example.yml` — starter alert rules
