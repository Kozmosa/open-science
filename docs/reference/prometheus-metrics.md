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

## Tasks

| Metric | Type | Labels | Emitted When |
|--------|------|--------|--------------|
| `ainrf_task_created_total` | Counter | _(none)_ | A new task is created |
| `ainrf_task_completed_total` | Counter | _(none)_ | A task reaches a terminal success state |
| `ainrf_task_failed_total` | Counter | _(none)_ | A task reaches a terminal failure state |

> **Note**: `ainrf_task_created_total`, `ainrf_task_completed_total`, and `ainrf_task_failed_total` are **not pre-declared** with label dimensions — they are lazily created. This means their TYPE/HELP lines only appear in `/metrics` output after at least one increment. If you see `total` in a PromQL query but not in the metrics endpoint, check that the corresponding code path has been exercised.

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
| `ainrf_files_sensitive_path_access_total` | Counter | _(none)_ | The file browser attempts to access a sensitive path (e.g. `/etc/passwd`) |

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

## Literature Tracking (arXiv Fetcher)

Metrics for the periodic arXiv paper discovery and LLM summarization pipeline (APScheduler, 6-hour interval by default).

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_literature_fetch_total` | Counter | `subscription_id`, `status` (`success` / `failed`) | Each subscription fetch attempt completes (or raises) | `literature/scheduler.py` |
| `ainrf_literature_papers_fetched_total` | Counter | `subscription_id` | arXiv API returns papers (count is the number returned, regardless of duplicates) | `literature/scheduler.py` |
| `ainrf_literature_papers_new_total` | Counter | `subscription_id` | New (non-duplicate) papers are inserted into the database | `literature/scheduler.py` |
| `ainrf_literature_summarize_total` | Counter | `status` (`success` / `failed`) | Each per-paper LLM summarize call completes (or fails) | `literature/fetcher.py` |
| `ainrf_literature_fetch_duration_seconds` | Histogram | `subscription_id` | Each subscription fetch attempt (arXiv query + LLM summarization) ends | `literature/scheduler.py` |
| `ainrf_literature_summarize_duration_seconds` | Histogram | _(none)_ | Each individual paper summarization LLM call ends | `literature/fetcher.py` |
| `ainrf_literature_last_fetch_timestamp_seconds` | Gauge | `subscription_id` | A subscription fetch succeeds (set to `time.time()` — Unix epoch seconds) | `literature/scheduler.py` |

**Derived PromQL** (examples):

- Fetch success rate per subscription:
  ```
  rate(ainrf_literature_fetch_total{status="success"}[1h])
  / rate(ainrf_literature_fetch_total[1h])
  ```
- Time since last successful fetch (staleness check):
  ```
  time() - ainrf_literature_last_fetch_timestamp_seconds > 21600
  ```
- Summarize success rate:
  ```
  rate(ainrf_literature_summarize_total{status="success"}[1h])
  / rate(ainrf_literature_summarize_total[1h])
  ```
- Duplicate rate (fraction of papers already in database):
  ```
  1 - (rate(ainrf_literature_papers_new_total[1h]) / rate(ainrf_literature_papers_fetched_total[1h]))
  ```

---

## SLA (Service Level Agreement)

Defined in `src/ainrf/api/routes/sla_metrics.py`. These metrics are created directly via the `prometheus_client` library (not through the pre-declaration mechanism in `metrics.py`).

| Metric | Type | Labels | Emitted When | Call Site |
|--------|------|--------|--------------|-----------|
| `ainrf_sla_task_completion_seconds` | Histogram | `status` (succeeded / failed / cancelled) | A task transitions from running to a terminal status | `sla_metrics.py` → `record_task_completed()` |
| `ainrf_sla_llm_first_token_seconds` | Histogram | `model` | First contentful token received from an LLM call | `sla_metrics.py` → `record_llm_first_token_latency()` |
| `ainrf_sla_tasks_total` | Counter | `status`, `researcher_type`, `harness_engine` | A task completes (any outcome) | `sla_metrics.py` → `record_task_completed()` |
| `ainrf_sla_uptime_seconds` | Gauge | _(none)_ | Set on first call to `record_uptime()` (periodic refresh) | `sla_metrics.py` → `record_uptime()` |
| `ainrf_rate_limited_total` | Counter | `reason` (`concurrency` / `ip_quota` / …), `path` | A request is rejected by rate limiting middleware or client-logs quota | `sla_metrics.py` → `rate_limited()` |

**SLA histogram buckets**:

- `ainrf_sla_task_completion_seconds`: 60s, 5min, 10min, 15min, 30min, 1h, 2h
- `ainrf_sla_llm_first_token_seconds`: 0.1s, 0.25s, 0.5s, 1s, 2.5s, 5s, 10s, 30s, 60s

> All other histograms (HTTP, SSH, DB, Literature) use the default buckets: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s.

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
| Subsystem grouping | `ainrf_literature_*`, `ainrf_sla_*`, `ainrf_ssh_*` |

Histogram bucket suffixes (`_bucket`, `_sum`, `_count`) are added automatically by `prometheus_client` and are not part of the declared metric name.

---

## Prometheus Alerting Rules

Alerting rules are at `deploy/config/prometheus/rules/ainrf-alerts.yml`. The bundled example at `deploy/examples/prometheus-rules.example.yml` provides a starter set (see Section 5 of the [observability stack design doc](../superpowers/specs/2026-06-15-observability-stack-design.md) for the full 14-rule inventory).

---

## Related Documents

- [Observability Stack Architecture](../superpowers/specs/2026-06-15-observability-stack-design.md) — design spec for the three-layer observability system
- `src/ainrf/api/routes/metrics.py` — metric pre-declaration table, public mutation API, exposition endpoint
- `src/ainrf/api/routes/sla_metrics.py` — SLA metrics definitions and recording helpers
- `src/ainrf/api/routes/client_metrics.py` — client-side web vitals ingestion endpoint
- `deploy/examples/prometheus-rules.example.yml` — starter alert rules
