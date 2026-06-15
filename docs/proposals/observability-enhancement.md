# Observability Enhancement Proposal

> **Status:** ✅ Implemented (Phase 0–2 complete, 2026-06-15)  
> **Date:** 2026-06-15  
> **Scope:** Metrics, logging, tracing, SLA tracking, alerting — backend + frontend + deployment  
> **Design spec:** [[2026-06-15-observability-stack-design]]  
> **Commits:** `6ed8d04` (P0), `5fa7644` (P1), `84217c3` (P2)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Assessment](#2-current-state-assessment)
3. [Target Architecture](#3-target-architecture)
4. [Phase 0 — Critical Fixes (P0)](#4-phase-0--critical-fixes-p0)
5. [Phase 1 — Structural Upgrades (P1)](#5-phase-1--structural-upgrades-p1)
6. [Phase 2 — Long-term Investments (P2)](#6-phase-2--long-term-investments-p2)
7. [Dependency Changes](#7-dependency-changes)
8. [Timeline & Dependencies](#8-timeline--dependencies)
9. [Risks & Mitigations](#9-risks--mitigations)
10. [Appendix: File Manifest](#10-appendix-file-manifest)

---

## 1. Executive Summary

The project has a **functional homegrown observability stack** (Prometheus-compatible metrics, structlog JSON logging, Litefuse LLM tracing, Grafana dashboards). However, several issues limit its production readiness:

- **Memory leak** in histogram storage (unbounded `list[float]` accumulation)
- **Disconnected trace hierarchy** in Litefuse (generations orphaned from traces)
- **Missing global exception handling** (inconsistent error responses, no request_id on 500s)
- **No distributed tracing** (no upstream trace context propagation)
- **Hand-rolled metrics** are fragile and lack features (no quantile estimation, no registry)
- **No SLA tracking** (no SLO definitions, no SLA dashboards, no breach alerting)

This proposal defines a phased plan to migrate to production-grade libraries (`prometheus_client`, OpenTelemetry SDK), fix critical bugs, add SLA tracking, and complete the observability picture end-to-end.

---

## 2. Current State Assessment

### 2.1 What works well

| Component | Implementation | Strengths |
|-----------|---------------|-----------|
| Structured logging | `structlog` → JSON → rotating files + stdout | Thread-safe context propagation, idempotent config |
| LLM tracing | Litefuse (Langfuse SDK) via `ObservabilityReporter` ABC | Clean DI pattern, graceful degradation, `SafeReporter` wrapper |
| Prometheus metrics | Hand-rolled dicts + lock → `/metrics` text format | Zero dependencies, custom path normalization |
| Grafana dashboards | Pre-provisioned "AINRF Overview" (14 panels) | Rich coverage, auth-gated via nginx |
| Alerting rules | 5 production rules in `ainrf-alerts.yml` | Covers HTTP, tasks, SSH, DB |
| Request tracing | `request_context.py` → `X-Request-ID` header + structlog context | Simple, effective within single service |
| Health check | `/health` with container + runtime readiness | Docker healthcheck integration |
| Frontend monitoring tab | Dynamic service discovery from backend API | Clean UX, relative/external URL handling |
| Client error ingestion | `POST /client-logs` with rate limiting | Endpoint exists, rate limited per IP |

### 2.2 Critical issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 1 | **Histogram memory leak** — observations never pruned | `metrics.py:96` | OOM on long-running instances |
| 2 | **Trace-generation disconnection** — `record_generation` doesn't pass `trace_id` to Litefuse SDK | `litefuse_reporter.py:117-126` | Orphaned LLM calls in Litefuse UI |
| 3 | **No global exception handler** — unhandled exceptions get FastAPI default 500 (no `request_id`, no `error_code`) | `app.py` (missing) | Inconsistent error responses |
| 4 | **No upstream trace context** — ignores incoming `X-Request-ID` / `traceparent` | `request_context.py:24` | Broken distributed tracing |
| 5 | **`QueryTimer` never receives SQL text** — slow query logs always show `"(unknown)"` | `instrumentation.py:54-65` vs `109` | Useless slow-query logs |
| 6 | **Hand-rolled metrics** — no quantile estimation, no type registry, manual render | `metrics.py:19-186` | Fragile, feature-poor |

### 2.3 Structural gaps

| # | Gap | Impact |
|---|-----|--------|
| 7 | No SLA/SLO definitions or tracking | Cannot measure service quality |
| 8 | No centralized log aggregation (all containers use `json-file` driver) | Logs scattered across containers |
| 9 | Frontend `ErrorBoundary` only logs to `console.error` | React crashes never reach backend |
| 10 | No per-user/IP rate limiting for API endpoints | Abuse surface; only global concurrency semaphore |
| 11 | Rate-limited/denied requests not counted in metrics | Invisible in dashboards |
| 12 | `structlog.contextvars` leakage — only `request_id` is unbound, other keys may leak | Cross-request context pollution |
| 13 | Audit log schema is free-form (`**kwargs`), no consistent field names | Unqueryable audit trail |
| 14 | Prometheus remote write receiver enabled but not used | Wasted configuration |
| 15 | Alert rules only loaded from example file (`prometheus-rules.example.yml`), not `rules/*.yml` | Inconsistent; Docker mounts example, Prometheus config points to `rules/` |

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OBSERVABILITY TARGET                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐ │
│  │   Frontend    │   │   Backend     │   │   Infrastructure         │ │
│  │               │   │               │   │                          │ │
│  │ ErrorBoundary │   │ OTel Auto-    │   │ Prometheus (metrics)     │ │
│  │  → /client-   │   │ Instrumentation│   │ Grafana (dashboards)    │ │
│  │    logs       │   │  ├─ FastAPI    │   │ Litefuse (LLM traces)   │ │
│  │               │   │  ├─ SQLite3    │   │ Loki (log aggregation)  │ │
│  │ Web Vitals    │   │  └─ HTTPX      │   │                          │ │
│  │  → /client-   │   │               │   │                          │ │
│  │    metrics    │   │ prometheus_    │   │                          │ │
│  │               │   │ client SDK     │   │                          │ │
│  │               │   │  → /metrics    │   │                          │ │
│  │               │   │               │   │                          │ │
│  │               │   │ structlog      │   │                          │ │
│  │               │   │  → stdout +    │   │                          │ │
│  │               │   │    file        │   │                          │ │
│  │               │   │               │   │                          │ │
│  │               │   │ LitefuseReporter│  │                          │ │
│  │               │   │  → Litefuse    │   │                          │ │
│  │               │   │    backend     │   │                          │ │
│  │               │   │               │   │                          │ │
│  │               │   │ SLA Metrics    │   │                          │ │
│  │               │   │  → Prometheus  │   │                          │ │
│  └──────────────┘   └──────────────┘   └──────────────────────────┘ │
│                                                                      │
│  Trace context flow:                                                 │
│  Client → Nginx → Backend (OTel Span) → Litefuse (LLM Span)          │
│              ↑                                                        │
│         X-Request-ID / traceparent propagated end-to-end              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Key design decisions

1. **`prometheus_client` replaces hand-rolled metrics** — industry standard, solves histogram memory, provides quantile estimation via `Histogram.observe()` bucketing.
2. **OpenTelemetry for auto-instrumentation only** — not for metrics (Prometheus already covers that). OTel auto-instruments FastAPI, SQLite3, and HTTPX with zero manual call-site code.
3. **Litefuse stays as LLM observability backend** — it works; fixes are surgical (trace ID propagation). No migration needed.
4. **Loki added for log aggregation** — all containers ship structured JSON to Loki via `loki-docker-driver`; Grafana already present as the query frontend.
5. **SLA tracking as a new metrics module** — defines SLO indicators, adds Grafana panels and Prometheus alert rules.

---

## 4. Phase 0 — Critical Fixes (P0)

These must be addressed first — they fix memory safety, data integrity, and basic debuggability.

### 4.1 [P0-1] Replace hand-rolled metrics with `prometheus_client`

**Problem:** `metrics.py` stores histogram observations as unbounded `list[float]` (line 96), accumulating all data points over process lifetime. On a server handling thousands of requests, this causes an OOM. Furthermore, PromQL's `histogram_quantile()` cannot compute accurate quantiles from cumulative sum/count — it requires bucket counts that the current code doesn't track correctly (it iterates all observations per render).

**Solution:** Replace the entire hand-rolled metrics storage and rendering with the official `prometheus_client` library.

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/api/routes/metrics.py` | **Rewrite.** Replace hand-rolled dicts with `prometheus_client.Counter`, `Histogram`, `Gauge`. Keep only the router factory and HTTP metrics middleware (but wire them to `prometheus_client` objects). |
| `src/ainrf/db/instrumentation.py` | Update imports: `from ainrf.api.routes.metrics import inc_counter, observe_histogram` → use the new `prometheus_client` metric objects directly or via thin wrapper. |
| `src/ainrf/api/routes/client_logs.py:78` | Update `inc_counter("ainrf_client_error_events_total")` → new API. |
| `src/ainrf/agentic_researcher/service.py` | Update any direct metric calls to use new metric objects. |

**Key implementation details:**

```python
# New metrics.py skeleton
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST

# HTTP metrics
http_requests_total = Counter(
    "ainrf_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "ainrf_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ... all other metrics follow same pattern ...

def get_metrics_text() -> str:
    """Return Prometheus text format from the default registry."""
    return generate_latest(REGISTRY).decode("utf-8")

def reset_metrics() -> None:
    """Reset all metrics (for testing)."""
    # Unregister all collectors from the default registry
    collectors = list(REGISTRY._collector_to_names.keys())
    for c in collectors:
        REGISTRY.unregister(c)
    # Re-import to re-register (test helper)
```

**Benefits over hand-rolled:**
- Built-in histogram bucketing → `histogram_quantile()` works correctly in PromQL.
- Fixed memory per metric (bucket counts, not raw observations).
- Standard `generate_latest()` renders correct Prometheus exposition format.
- No thread-lock management needed.
- Ready for OpenMetrics format when needed.

**Acceptance criteria:**
- [ ] All 19 existing metrics migrated to `prometheus_client` types.
- [ ] `GET /metrics` returns correct Prometheus exposition format.
- [ ] Existing Grafana dashboard panels still work (metric names unchanged).
- [ ] `reset_metrics()` works correctly for test isolation.
- [ ] No memory growth under sustained load (histogram uses fixed bucket arrays).

---

### 4.2 [P0-2] Fix Litefuse trace-generation association

**Problem:** `record_generation()` at `litefuse_reporter.py:117-126` creates a Langfuse generation observation but **never passes `trace_id`**. All LLM calls appear as top-level orphaned observations in the Litefuse UI, disconnected from the task trace created by `start_trace()`.

**Solution:** Modify `record_generation()` and `record_span()` to pass the `trace_id` when creating observations, so they nest under the correct trace.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/observability/litefuse_reporter.py` | Pass `trace_context={"trace_id": trace_id}` to `start_as_current_observation()` in `record_generation()` and `record_span()`. |
| `src/ainrf/observability/protocol.py` | Add `duration_ms: float | None = None` parameter to `record_generation` and `record_span` for completeness. |

**Key implementation detail:**

```python
def record_generation(self, trace_id: str, name: str, *, ...) -> None:
    ctx = self._client.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=input,
        trace_context={"trace_id": trace_id},  # ← THIS WAS MISSING
    )
    gen = ctx.__enter__()
    # ... update metadata ...
    ctx.__exit__(None, None, None)
```

Additionally, `start_trace()` should use Langfuse's trace-first API rather than creating a "span" observation with `trace_context`. The standard approach is:

```python
def start_trace(self, trace_id: str, name: str, *, ...) -> None:
    trace = self._client.start_as_current_observation(
        as_type="trace",
        name=name,
        input=input,
        metadata=metadata,
    )
    self._active_traces[trace_id] = trace
```

**Acceptance criteria:**
- [ ] Generation observations appear nested under their parent trace in the Litefuse UI.
- [ ] Span observations appear nested under their parent trace.
- [ ] Backward compatible: existing `ObservabilityReporter` callers work without changes.
- [ ] `NullReporter` and `SafeReporter` signatures updated consistently.

---

### 4.3 [P0-3] Add global exception-handling middleware

**Problem:** There is no global FastAPI exception handler. Unhandled exceptions propagate through `request_logging.py` (which catches, logs, and re-raises) and `build_http_metrics_middleware` (same pattern), then FastAPI returns a generic `{"detail": "Internal Server Error"}` without `request_id` or structured `error_code`. The `raise_structured_error()` utility exists but is opt-in and unused by any route.

**Solution:** Add a catch-all exception middleware at the innermost position (closest to the app), and migrate existing routes to use `raise_structured_error()`.

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/api/middleware/exception_handler.py` | **New file.** Middleware that catches all unhandled exceptions, logs with `request_id`, and returns structured `{error_code, message, request_id}` response. |
| `src/ainrf/api/app.py` | Register new middleware at the innermost position (after auth, before metrics). |
| `src/ainrf/api/errors.py` | Enhance `raise_structured_error()` to auto-extract `request_id` from `structlog.contextvars` if not explicitly passed. |

**Key implementation:**

```python
# exception_handler.py
import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi import HTTPException

_LOG = structlog.get_logger("exception_handler")

async def exception_handler_middleware(request: Request, call_next) -> Response:
    try:
        return await call_next(request)
    except HTTPException:
        raise  # Already handled by FastAPI
    except asyncio.CancelledError:
        raise  # Never swallow cancellation
    except Exception:
        request_id = getattr(request.state, "request_id", "-")
        _LOG.error(
            "unhandled_exception",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An internal error occurred. Please retry or contact support.",
                "request_id": request_id,
            },
        )
```

**Acceptance criteria:**
- [ ] All unhandled exceptions return `{"error_code": "INTERNAL_ERROR", "message": "...", "request_id": "..."}`.
- [ ] `HTTPException` (4xx/5xx from route handlers) are NOT caught (FastAPI handles them).
- [ ] `asyncio.CancelledError` is NOT caught (would break cancellation semantics).
- [ ] Structured error logged via structlog with full traceback and `request_id`.
- [ ] `raise_structured_error()` auto-includes `request_id` from context.

---

### 4.4 [P0-4] Accept upstream trace context

**Problem:** `request_context.py` always generates a new UUID. If nginx or an API gateway sends an `X-Request-ID` or W3C `traceparent` header, it's ignored. This breaks distributed trace correlation across service boundaries.

**Solution:** Read incoming `X-Request-ID` header first; if present, use it. If not, generate a new UUID. Additionally, parse W3C `traceparent` for the trace ID and set it on `request.state.trace_id`.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/api/middleware/request_context.py` | Read `X-Request-ID` header → use if present, else generate UUID. Parse `traceparent` header → store `trace_id` on `request.state`. Bind both to structlog contextvars. Unbind all bound keys in `finally` block (not just `request_id`). |
| `src/ainrf/api/errors.py` | Extract `trace_id` in addition to `request_id`. |

**Key implementation:**

```python
# request_context.py (updated)
_TRACEPARENT_RE = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)

async def request_context_middleware(request, call_next):
    # Accept upstream request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    # Parse W3C traceparent for distributed tracing
    trace_id = None
    tp = request.headers.get("traceparent", "")
    m = _TRACEPARENT_RE.match(tp)
    if m:
        trace_id = m.group(2)  # 32-char hex trace ID
    request.state.trace_id = trace_id

    # Bind to structlog context
    bindings = {"request_id": request_id}
    if trace_id:
        bindings["trace_id"] = trace_id
    structlog.contextvars.bind_contextvars(**bindings)

    try:
        response = await call_next(request)
    finally:
        # Unbind ALL keys we bound (prevents context leakage)
        for key in bindings:
            structlog.contextvars.unbind_contextvars(key)

    response.headers["X-Request-ID"] = request_id
    if trace_id:
        response.headers["traceresponse"] = f"00-{trace_id}-..."
    return response
```

**Acceptance criteria:**
- [ ] Incoming `X-Request-ID` header is used as `request_id` (not overwritten).
- [ ] Incoming `traceparent` header is parsed, `trace_id` propagated to logs.
- [ ] Response includes `X-Request-ID` and `traceresponse` headers.
- [ ] All bound contextvars are unbound in `finally` (no leakage).
- [ ] Backward compatible: no `X-Request-ID` header → new UUID generated.

---

### 4.5 [P0-5] Fix `QueryTimer` SQL text propagation

**Problem:** `instrument_connection()` sets a SQLite trace callback that stores SQL text in `last_sql[0]` (line 54-65), but `QueryTimer` never reads it. The slow query log at line 109 always shows `"(unknown)"`.

**Solution:** Wire the trace callback's `last_sql` to `QueryTimer` by passing a shared container, or store the last SQL on the connection object and have `QueryTimer` read it.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/db/instrumentation.py` | Store `last_sql` on the connection object (`conn._ainrf_last_sql`). `QueryTimer.__exit__` reads from `conn._ainrf_last_sql`. Update `QueryTimer` to accept an optional `conn` parameter. |

**Key implementation:**

```python
def instrument_connection(conn, db_label, *, slow_threshold=1.0, trace_all=False):
    # Store shared state on the connection
    conn._ainrf_db_label = db_label
    conn._ainrf_last_sql = [""]

    def _on_sql(sql: str) -> None:
        if trace_all:
            _LOG.debug("db_query", db=db_label, sql=sql[:200])
        conn._ainrf_last_sql[0] = sql

    conn.set_trace_callback(_on_sql)
    return conn


class QueryTimer:
    def __init__(self, db_label, *, slow_threshold=1.0, sql="", conn=None):
        self._label = db_label
        self._threshold = slow_threshold
        self._explicit_sql = sql
        self._conn = conn
        self.elapsed = 0.0

    @property
    def sql(self) -> str:
        if self._explicit_sql:
            return self._explicit_sql
        if self._conn and hasattr(self._conn, "_ainrf_last_sql"):
            return self._conn._ainrf_last_sql[0]
        return "(unknown)"
```

**Acceptance criteria:**
- [ ] Slow query logs show actual SQL text, not `"(unknown)"`.
- [ ] `QueryTimer` accepts optional `conn` parameter for auto-discovery.
- [ ] Explicit `sql` parameter still takes precedence.

---

## 5. Phase 1 — Structural Upgrades (P1)

These build on P0 fixes to add SLA tracking, better health checks, structured audit logging, OpenTelemetry auto-instrumentation, and a consistent contextvar lifecycle.

### 5.1 [P1-1] SLA metrics and dashboards

**Problem:** The project has no SLA/SLO framework. There's no way to measure task completion latency, LLM first-token time, or overall availability against defined objectives.

**Solution:** Define SLO indicators, implement them as Prometheus metrics, add Grafana panels, and configure alert rules for breaches.

**SLO Definitions:**

| SLO | Metric | Target | Window |
|-----|--------|--------|--------|
| Availability | `ainrf_http_requests_total{status!~"5.."}` / total | ≥ 99.5% | 30d |
| Task completion P95 | `ainrf_sla_task_completion_seconds` histogram | ≤ 30 min | rolling |
| LLM first-token P99 | `ainrf_sla_llm_first_token_seconds` histogram | ≤ 10s | rolling |
| Error budget | Derived from availability SLO | Burn rate alert | — |

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/api/routes/sla_metrics.py` | **New file.** Define SLA-specific Prometheus metrics (task latency, first-token latency, uptime gauge). |
| `src/ainrf/agentic_researcher/service.py` | Record `task_completion_seconds` at `end_trace()` time. (Already has start/end timestamps — just record the delta.) |
| `src/ainrf/agentic_researcher/service.py` | Record `llm_first_token_seconds` in `_handle_engine_event()` when first token arrives. |
| `deploy/config/grafana/dashboards/ainrf/ainrf-overview.json` | Add SLA panels: availability gauge, task P95, LLM P99, error budget burn rate. |
| `deploy/config/prometheus/rules/ainrf-alerts.yml` | Add SLA breach alert rules. |
| `src/ainrf/api/routes/health.py` | Add uptime counter for availability calculation. |

**New alert rules:**

```yaml
- alert: AINRFTaskCompletionSLABreach
  expr: |
    histogram_quantile(0.95,
      sum(rate(ainrf_sla_task_completion_seconds_bucket[1h])) by (le)
    ) > 1800
  for: 1h
  labels:
    severity: critical
    component: sla
  annotations:
    summary: "Task completion P95 exceeds 30-minute SLO"

- alert: AINRFLLMFirstTokenSLABreach
  expr: |
    histogram_quantile(0.99,
      sum(rate(ainrf_sla_llm_first_token_seconds_bucket[30m])) by (le)
    ) > 10
  for: 30m
  labels:
    severity: warning
    component: sla

- alert: AINRFErrorBudgetBurn
  expr: |
    (
      sum(rate(ainrf_http_requests_total{status=~"5.."}[1h]))
      / sum(rate(ainrf_http_requests_total[1h]))
    ) > 0.005 * 14.4
  for: 1h
  labels:
    severity: critical
    component: sla
  annotations:
    summary: "Error budget burn rate exceeds 14.4x (critical)"
```

**Acceptance criteria:**
- [ ] `ainrf_sla_task_completion_seconds` histogram recorded for every completed/failed task.
- [ ] `ainrf_sla_llm_first_token_seconds` histogram recorded for every LLM call.
- [ ] Grafana dashboard has dedicated SLA row with gauge + time-series panels.
- [ ] Three new SLA alert rules active in Prometheus.
- [ ] SLO targets documented in code and operations runbook.

---

### 5.2 [P1-2] Enhanced health check

**Problem:** `/health` currently checks only binary availability (`tmux`, `uv` on `$PATH`). It does not verify database connectivity, Litefuse backend health, or external dependencies.

**Solution:** Add optional component-level health checks with structured status.

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/api/routes/health.py` | Add `HealthCheck` protocol, implement checks for SQLite (SELECT 1), Litefuse (existing `is_healthy()`), filesystem (writable state dir). Return `{status, checks: {db, litefuse, filesystem, runtime}}`. |
| `src/ainrf/api/schemas.py` | Update `HealthResponse` model with `checks: dict[str, ComponentHealth]`. |

**Response schema:**

```python
class ComponentHealth(BaseModel):
    status: Literal["ok", "degraded", "unhealthy"]
    latency_ms: float | None = None
    error: str | None = None

class HealthResponse(BaseModel):
    status: ApiStatus  # "ok" | "degraded"
    checks: dict[str, ComponentHealth]  # "db", "litefuse", "filesystem", "runtime"
    uptime_seconds: float
    state_root: str
    # ... existing fields ...
```

**Acceptance criteria:**
- [ ] `/health` returns per-component status.
- [ ] DB health check runs `SELECT 1`.
- [ ] Litefuse health check uses `reporter.is_healthy()`.
- [ ] Overall `status` is `"degraded"` if any non-critical component is unhealthy.
- [ ] Docker healthcheck still works (only uses HTTP status code).
- [ ] No health check takes longer than 2 seconds (timeout per check).

---

### 5.3 [P1-3] Structured audit log schema

**Problem:** `audit.py` accepts free-form `**kwargs`. There is no consistent schema across call sites. Over time, different developers use different key names for the same concepts (`user_id` vs `actor` vs `username`). This makes querying audit logs unreliable.

**Solution:** Define a typed `AuditEvent` schema with mandatory and optional fields.

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/security/audit.py` | Define `AuditEvent` dataclass with fields: `action`, `actor_id`, `actor_type`, `resource_id`, `resource_type`, `result`, `details`, `client_ip`, `request_id`. Add `emit_audit(event: AuditEvent)` as the primary API. Keep `audit_event()` as a deprecated compatibility wrapper. |
| All call sites | Migrate to `emit_audit(AuditEvent(...))` over time. |

**Schema:**

```python
@dataclass(slots=True)
class AuditEvent:
    action: str              # "user.login", "file.sensitive_access", "task.create"
    result: str              # "success", "failure", "denied"
    actor_id: str | None = None
    actor_type: str = "user" # "user", "api_key", "system"
    resource_id: str | None = None
    resource_type: str | None = None  # "task", "workspace", "file", "session"
    details: dict[str, Any] | None = None  # Supplementary context
    severity: str = "info"   # "info", "warning", "error", "critical"
```

**Acceptance criteria:**
- [ ] `AuditEvent` dataclass defined with all fields.
- [ ] `emit_audit()` function auto-extracts `request_id` from structlog contextvars.
- [ ] All existing `audit_event()` call sites migrated or confirmed compatible.
- [ ] Documentation updated with audit event catalog.

---

### 5.4 [P1-4] OpenTelemetry auto-instrumentation (FastAPI + SQLite3 + HTTPX)

**Problem:** Every instrumentation point is manual: developers must remember to wrap SQLite queries in `QueryTimer`, call `start_trace`/`end_trace` in service methods, and record HTTP metrics by hand. New endpoints or database operations are invisible until someone manually adds instrumentation.

**Solution:** Introduce OpenTelemetry SDK with auto-instrumentation for FastAPI, SQLite3, and HTTPX. OTel spans provide automatic distributed tracing context. Metrics remain on Prometheus. Litefuse remains for LLM-specific observability.

**Scope:** This phase introduces OTel **auto-instrumentation only** (spans/traces). It does NOT replace Prometheus metrics or Litefuse LLM tracing. The three systems coexist:
- **OTel** → automatic HTTP/db/HTTP-client spans (replaces hand-rolled `request_logging` timing, `QueryTimer`)
- **Prometheus** → metrics (replaces hand-rolled `metrics.py` types)
- **Litefuse** → LLM-specific generation/token tracing (unchanged)

**What changes:**

| File | Action |
|------|--------|
| `pyproject.toml` | Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlite3`, `opentelemetry-instrumentation-httpx`, `opentelemetry-exporter-otlp-proto-http` |
| `src/ainrf/telemetry/` | **New package.** `__init__.py` (OTel SDK init), `config.py` (env var reading), `middleware.py` (OTel-FastAPI integration). |
| `src/ainrf/api/app.py` | Call `init_telemetry()` at startup. |
| `src/ainrf/db/instrumentation.py` | **Deprecate** manual `QueryTimer` in favor of OTel auto-instrumentation. Keep for backward compatibility. |
| `src/ainrf/api/middleware/request_logging.py` | Keep logging (method/path/status/duration) but remove manual timing (OTel span provides this). |
| `src/ainrf/logging.py` | Add OTel trace context injection into structlog (via `opentelemetry-instrumentation-logging` or manual processor). |

**Architecture decision — exporter target:** Initially, export OTel spans to the Litefuse backend (since Litefuse is a Langfuse fork, and Langfuse supports OTLP ingest). If that's not desired, a local Jaeger or no-op exporter can be used. Configured via `AINRF_OTEL_EXPORTER_ENDPOINT` env var.

**Key implementation:**

```python
# src/ainrf/telemetry/__init__.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.httpx import HTTPXInstrumentor


def init_telemetry(app, config) -> None:
    if not config.otel_enabled:
        return

    resource = Resource(attributes={
        SERVICE_NAME: "ainrf",
        "deployment.environment": config.deployment_env,
    })
    provider = TracerProvider(resource=resource)

    if config.otel_exporter_endpoint:
        exporter = OTLPSpanExporter(endpoint=config.otel_exporter_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # Auto-instrument
    FastAPIInstrumentor.instrument_app(app)
    SQLite3Instrumentor().instrument()
    HTTPXInstrumentor().instrument()
```

**Migration path for `QueryTimer`:**
1. Phase 1: OTel auto-instruments all SQLite3 calls. `QueryTimer` becomes a no-op wrapper that logs a deprecation warning.
2. Phase 2 (in P2): Remove `QueryTimer` entirely; all call sites simplified.

**Acceptance criteria:**
- [ ] OTel SDK initializes without error when `AINRF_OTEL_ENABLED=true`.
- [ ] Every HTTP request generates an OTel span with `http.method`, `http.url`, `http.status_code`.
- [ ] Every SQLite query generates an OTel span with `db.system=sqlite`, `db.statement`.
- [ ] OTel trace ID and span ID are injected into structlog context (log-trace correlation).
- [ ] OTel exporter gracefully degrades if endpoint is unreachable (doesn't crash the app).
- [ ] `AINRF_OTEL_ENABLED=false` (default) → zero overhead, no SDK init.

---

### 5.5 [P1-5] Rate-limiting instrumentation

**Problem:** The concurrency limit middleware returns `503` without incrementing any Prometheus counter. The `/client-logs` rate limiter returns `429` without incrementing any metric. Rate-limited requests are invisible.

**Solution:** Add `ainrf_rate_limited_total` counter with labels `reason` and `path`.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/api/middleware/__init__.py` (concurrency limiter) | Increment `rate_limited_total{reason="concurrency"}` before returning 503. |
| `src/ainrf/api/routes/client_logs.py` | Increment `rate_limited_total{reason="ip_quota"}` before returning 429. |
| `deploy/config/grafana/dashboards/ainrf/ainrf-overview.json` | Add rate-limiting panel. |

**Acceptance criteria:**
- [ ] `ainrf_rate_limited_total` counter exists with `reason` label.
- [ ] Concurrency-limit 503s increment the counter.
- [ ] `/client-logs` 429s increment the counter.
- [ ] Rate-limiting visible in Grafana dashboard.

---

### 5.6 [P1-6] Contextvars lifecycle hardening

**Problem:** `request_context.py` only unbinds `request_id` in its `finally` block. If other middleware or code binds additional contextvars (e.g., `task_id` in `service.py`), they may leak across requests if their unbind is missed.

**Solution:** Track all bound keys and unbind them deterministically. In `request_context.py`, snapshot the keys before binding and unbind only the delta. In `service.py`, ensure `task_id` is always unbound.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/api/middleware/request_context.py` | Snapshot existing contextvars keys before binding, unbind delta in finally. |
| `src/ainrf/agentic_researcher/service.py` | Audit all `bind_contextvars` calls — ensure every one has a matching `unbind` in a `finally` block. |
| `src/ainrf/api/middleware/request_logging.py` | Move structlog binding out (already done by request_context); only read contextvars. |

**Implementation pattern:**

```python
# Snapshot-based unbind
import structlog

bound_keys = {"request_id": request_id}
if trace_id:
    bound_keys["trace_id"] = trace_id

# Get currently bound keys before adding ours
existing_keys = set(structlog.contextvars._contextvars_context.get({}).keys())
structlog.contextvars.bind_contextvars(**bound_keys)

try:
    response = await call_next(request)
finally:
    # Unbind only what we added
    for key in bound_keys:
        structlog.contextvars.unbind_contextvars(key)
```

**Acceptance criteria:**
- [ ] No contextvar leaks across requests (verifiable via test that sends two requests and checks for stale keys).
- [ ] `service.py` has `finally` blocks for all `bind_contextvars` calls.
- [ ] Test added: `test_no_contextvar_leakage`.

---

## 6. Phase 2 — Long-term Investments (P2)

These provide the highest long-term value but require the most effort and infrastructure changes.

### 6.1 [P2-1] Centralized log aggregation with Loki

**Problem:** All Docker containers use `json-file` logging driver. Logs are scattered across containers and lost on container restart. There's no centralized log search.

**Solution:** Add Loki to the Docker Compose stack. Use `loki-docker-driver` (or `promtail`) to ship all container logs to Loki. Grafana already exists as the query frontend — just add a Loki datasource.

**What changes:**

| File | Action |
|------|--------|
| `deploy/docker-compose.yml` | Add `loki` service, update all services to use `loki` logging driver (or keep `json-file` + add `promtail`). |
| `deploy/config/grafana/provisioning/datasources/` | Add `loki.yml` datasource config. |
| `deploy/config/loki/loki-config.yml` | **New file.** Loki configuration (retention, storage, compactor). |
| `src/ainrf/logging.py` | (No changes needed — structlog already emits JSON, which Loki indexes natively.) |

**Docker Compose addition:**

```yaml
loki:
  image: docker.1ms.run/grafana/loki:3.5.0
  restart: unless-stopped
  container_name: ainrf-loki
  volumes:
    - ./config/loki/loki-config.yml:/etc/loki/local-config.yaml:ro
    - loki-data:/loki
  expose:
    - "3100"
  command: -config.file=/etc/loki/local-config.yaml
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"
```

**Log driver approach:** Use `loki-docker-driver` plugin for zero-config log shipping from all containers. Alternative: keep `json-file` driver and add `promtail` as a sidecar that tails `/var/lib/docker/containers/*/*.log`.

**Acceptance criteria:**
- [ ] Loki service running and healthy.
- [ ] All container logs shipped to Loki.
- [ ] Grafana has Loki datasource configured.
- [ ] Can query backend, nginx, and Litefuse logs from a single Grafana Explore view.
- [ ] Log retention: 30 days.

---

### 6.2 [P2-2] Frontend observability completion

**Problem:** The frontend `ErrorBoundary.componentDidCatch` only calls `console.error`. React crashes never reach the backend. The `POST /client-logs` endpoint already exists but nothing calls it. React Profiler data (`window.__perfProfilerData`) is collected but never sent.

**Solution:** Send `ErrorBoundary` catches to `POST /client-logs`. Add Web Vitals (LCP, FCP, INP, CLS) reporting via the existing endpoint. Add a new `POST /client-metrics` endpoint for Web Vitals specifically (or reuse `/client-logs` with a `type` discriminator).

**What changes:**

| File | Action |
|------|--------|
| `frontend/src/components/common/ErrorBoundary.tsx` | In `componentDidCatch`, send error to `POST /client-logs` with `fetch(..., { keepalive: true })`. |
| `frontend/src/shared/utils/errorBoundary.tsx` | Same change (duplicate ErrorBoundary). |
| `frontend/src/shared/utils/reportWebVitals.ts` | **New file.** Uses `web-vitals` library (or manual `PerformanceObserver`) to collect LCP, FCP, INP, CLS and POST to `/client-metrics`. |
| `frontend/src/App.tsx` | Call `reportWebVitals()` on mount. Also periodically flush `window.__perfProfilerData` to backend. |
| `src/ainrf/api/routes/client_logs.py` | Add support for `type: "web_vital"` events, or create a new `/client-metrics` endpoint. Add `ainrf_client_web_vitals_*` histograms. |

**Key implementation (frontend side):**

```typescript
// ErrorBoundary.tsx
componentDidCatch(error: Error, errorInfo: ErrorInfo) {
  console.error('ErrorBoundary caught:', error, errorInfo);
  // Fire-and-forget to backend
  fetch('/client-logs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      events: [{
        message: error.message,
        url: window.location.href,
        requestId: window.__currentRequestId ?? '-',
        userAgent: navigator.userAgent,
        stack: error.stack?.slice(0, 500) ?? '',
        metadata: { componentStack: errorInfo.componentStack?.slice(0, 1000) },
      }],
    }),
    keepalive: true,
  }).catch(() => {}); // Fire-and-forget
}
```

**Web Vitals collection:**

```typescript
// reportWebVitals.ts
import { onLCP, onFCP, onINP, onCLS } from 'web-vitals';

function sendToBackend(metric: { name: string; value: number; rating: string }) {
  fetch('/client-metrics', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      metrics: [{
        name: metric.name,
        value: metric.value,
        rating: metric.rating,
        url: window.location.pathname,
        timestamp: Date.now(),
      }],
    }),
    keepalive: true,
  }).catch(() => {});
}

export function reportWebVitals() {
  onLCP(sendToBackend);
  onFCP(sendToBackend);
  onINP(sendToBackend);
  onCLS(sendToBackend);
}
```

**Acceptance criteria:**
- [ ] React `ErrorBoundary` catches are POSTed to `/client-logs`.
- [ ] Web Vitals (LCP, FCP, INP, CLS) are POSTed to `/client-metrics`.
- [ ] Backend records Web Vitals as Prometheus histograms (`ainrf_client_lcp_seconds`, etc.).
- [ ] Grafana dashboard has a "Frontend" row with error rate and Web Vitals panels.
- [ ] No PII in error reports (stack traces filtered client-side).

---

### 6.3 [P2-3] Alert coverage expansion and Grafana Alerting

**Problem:** Only 5 alert rules are active. The example rules file (`prometheus-rules.example.yml`) has 6 additional rules that cover login failures, account lockouts, terminal exec denials, sensitive file access, and high request rate. These are not loaded. Additionally, there is no second alerting channel — Prometheus is the sole alert source.

**Solution:** Review, audit, and activate the example rules. Add Grafana Alerting as a second channel for dashboard-based alerts (e.g., "no data received for 10min"). Integrate with existing Feishu notification infrastructure.

**What changes:**

| File | Action |
|------|--------|
| `deploy/config/prometheus/rules/ainrf-alerts.yml` | Merge in the 6 example rules after reviewing thresholds. |
| `deploy/config/grafana/provisioning/alerting/` | **New directory.** Grafana Alerting configuration with contact points (Feishu webhook). |
| `deploy/docker-compose.yml` | Add Grafana alerting env vars (`GF_UNIFIED_ALERTING_ENABLED=true`, etc.). |

**New rules to activate:**

| Rule | Severity | Rationale |
|------|----------|-----------|
| `AINRFHighLoginFailureRate` | warning | Detect brute-force attacks |
| `AINRFAccountLockouts` | info | Detect credential stuffing |
| `AINRFTerminalExecDenials` | warning | Detect policy violations or misconfiguration |
| `AINRFSensitiveFileAccess` | high | Detect potential data exfiltration |
| `AINRFHighRequestRate` | warning | Detect DDoS or traffic anomaly |
| `AINRFNoMetrics` (Grafana) | critical | Detect metrics pipeline failure |

**Acceptance criteria:**
- [ ] 11 total Prometheus alert rules active (5 existing + 6 new).
- [ ] Grafana Alerting configured with Feishu webhook contact point.
- [ ] At least 2 Grafana-managed alerts (e.g., "No data", "Disk space low").
- [ ] Test alert fired and received on Feishu.

---

### 6.4 [P2-4] Prometheus remote write

**Problem:** The Prometheus container is started with `--web.enable-remote-write-receiver` (line 134 in docker-compose.yml) but no remote write target is configured. This is dead configuration.

**Solution:** Either:
1. **Remove the flag** if no remote write target is planned (cleanup).
2. **Configure a remote write target** (e.g., Grafana Cloud, a centralized Thanos/Cortex instance) if multi-cluster metric aggregation is needed.

**Recommendation:** Remove the flag for now. If a remote write target is needed later, it can be re-added with the actual endpoint.

**What changes:**

| File | Change |
|------|--------|
| `deploy/docker-compose.yml` (and `*.cpu.yml`, `*.gpu.yml`) | Remove `--web.enable-remote-write-receiver` from Prometheus command. |

**Acceptance criteria:**
- [ ] Prometheus starts cleanly without the unused remote write flag.

---

### 6.5 [P2-5] Per-user / per-IP API rate limiting

**Problem:** There is no per-user or per-IP rate limiting for general API endpoints. Only a global concurrency semaphore and a single-endpoint IP limiter (`/client-logs`) exist.

**Solution:** Add an optional rate-limiting middleware using a token-bucket or sliding-window algorithm, backed by in-memory storage (sufficient for single-process deployment). Gate it behind `AINRF_RATE_LIMIT_ENABLED`. Expose metrics via `ainrf_rate_limited_total{reason="user_quota"}` (extends P1-5).

**What changes:**

| File | Action |
|------|--------|
| `src/ainrf/api/middleware/rate_limit.py` | **New file.** Token-bucket rate limiter per authenticated user (or per IP if unauthenticated), configurable via env vars. |
| `src/ainrf/api/app.py` | Register rate limit middleware (after auth, before route handlers). |

**Configuration:**

```
AINRF_RATE_LIMIT_ENABLED=true
AINRF_RATE_LIMIT_REQUESTS_PER_MINUTE=60   # per user/IP
AINRF_RATE_LIMIT_BURST_SIZE=10            # token bucket burst
```

**Acceptance criteria:**
- [ ] Rate limiter returns `429` with `Retry-After` header when quota exceeded.
- [ ] Rate-limited requests recorded in `ainrf_rate_limited_total{reason="user_quota"}`.
- [ ] Default disabled (`AINRF_RATE_LIMIT_ENABLED=false`).
- [ ] No memory leak (periodic cleanup of expired buckets).

---

### 6.6 [P2-6] Remove deprecated `QueryTimer` and simplify call sites

**Problem:** After P1-4 (OTel auto-instrumentation), `QueryTimer` is redundant. All SQLite queries are automatically traced by OTel's `SQLite3Instrumentor`. Keeping `QueryTimer` means two timing mechanisms for every query.

**Solution:** Remove `QueryTimer` usage from all call sites. Keep `instrument_connection()` for the `db_label` duck-typing (useful for log context), but remove the timing/metrics responsibility.

**What changes:**

| File | Change |
|------|--------|
| `src/ainrf/db/instrumentation.py` | Mark `QueryTimer` as deprecated (or remove if no external consumers). |
| All call sites using `QueryTimer` | Remove the `with QueryTimer(...)` wrapper. |
| `src/ainrf/agentic_researcher/service.py` | Remove manual `QueryTimer` usage. |

**Acceptance criteria:**
- [ ] No `QueryTimer` usage in production code paths.
- [ ] All SQL queries still traced (via OTel auto-instrumentation).
- [ ] `ainrf_db_query_duration_seconds` histogram still recorded (from OTel metrics bridge or explicit Prometheus exporter).

---

## 7. Dependency Changes

### 7.1 Python dependencies (pyproject.toml)

```diff
[project]
dependencies = [
  "asyncssh>=2.21.1",
  "claude_agent_sdk>=0.1.77",
  "fastapi>=0.116.1",
  "httpx>=0.28.1",
  "pydantic>=2.11.7",
  "structlog>=25.4.0",
  "typer>=0.17.4",
  "uvicorn>=0.35.0",
  "websockets>=15.0.1",
  "pyyaml>=6.0.2",
  "bcrypt>=5.0.0",
  "pyjwt>=2.12.1",
  "arxiv>=4.0.0",
  "apscheduler>=3.11.2",
  "json-repair>=0.59.10",
  "langfuse>=2.0.0",
+ "prometheus-client>=0.22.0",
+ "opentelemetry-api>=1.30.0",
+ "opentelemetry-sdk>=1.30.0",
+ "opentelemetry-instrumentation-fastapi>=0.51b0",
+ "opentelemetry-instrumentation-sqlite3>=0.51b0",
+ "opentelemetry-instrumentation-httpx>=0.51b0",
+ "opentelemetry-exporter-otlp-proto-http>=1.30.0",
]
```

### 7.2 Frontend dependencies (optional, P2)

```diff
// package.json
{
  "dependencies": {
+   "web-vitals": "^4.2.0"
  }
}
```

### 7.3 Docker services

```diff
# docker-compose.yml
services:
+ loki:
+   image: docker.1ms.run/grafana/loki:3.5.0
+   ...
```

---

## 8. Timeline & Dependencies

```
Week 1-2 (Phase 0)
├── P0-1: prometheus_client migration     [3d]  ← no dependencies
├── P0-2: Litefuse trace fix              [1d]  ← no dependencies
├── P0-3: Global exception handler         [1d]  ← no dependencies
├── P0-4: Upstream trace context          [0.5d] ← no dependencies
└── P0-5: QueryTimer SQL propagation      [0.5d] ← no dependencies

Week 2-3 (Phase 1)
├── P1-1: SLA metrics + dashboards        [3d]  ← depends on P0-1 (needs prometheus_client)
├── P1-2: Enhanced health check           [1d]  ← no dependencies
├── P1-3: Structured audit schema         [1d]  ← no dependencies
├── P1-4: OpenTelemetry instrumentation   [3d]  ← independent (coexists with P0-1)
├── P1-5: Rate-limiting instrumentation   [0.5d] ← depends on P0-1
└── P1-6: Contextvars hardening           [1d]  ← no dependencies

Week 4-5 (Phase 2)
├── P2-1: Loki log aggregation            [2d]  ← no code dependencies (infra only)
├── P2-2: Frontend observability          [2d]  ← depends on P0-1 (needs client metrics histograms)
├── P2-3: Alert coverage expansion        [1d]  ← depends on P0-1, P1-1 (needs metrics)
├── P2-4: Prometheus remote write cleanup [0.2d] ← no dependencies
├── P2-5: Per-user rate limiting          [2d]  ← depends on P1-5
└── P2-6: QueryTimer removal              [1d]  ← depends on P1-4
```

**Total estimated effort:** ~22 working days

### Execution strategy

1. **P0 tasks can be parallelized** — all 5 are independent. Assign to different developers.
2. **P0-1 (prometheus_client) is the critical path** — P1-1, P1-5, P2-2, and P2-3 depend on it.
3. **P1-4 (OpenTelemetry) can run in parallel with P0-1** — they touch different files.
4. **P1 and P2 tasks can mostly run in parallel** once P0 is complete.

---

## 9. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| `prometheus_client` migration breaks existing Grafana dashboards | Medium | High | Keep metric names identical. Verify dashboard panels after migration. Add integration test that compares `/metrics` output before/after. |
| OTel SDK performance overhead | Low | Medium | Default OTel off (`AINRF_OTEL_ENABLED=false`). Use `BatchSpanProcessor` for async export. Benchmark before enabling in production. |
| Loki adds significant resource usage | Medium | Low | Start with 7-day retention, 2GB storage limit. Monitor container resource usage. |
| Langfuse SDK API changes break `LitefuseReporter` after refactor | Low | Medium | `SafeReporter` catches all exceptions. The reporter is non-critical (app runs fine without it). Pin `langfuse>=2.0.0,<3.0.0`. |
| Rate limiter memory leak | Low | Medium | Periodic cleanup goroutine for expired token buckets. Add Prometheus gauge for active rate-limit entries. |
| Frontend error reporting floods `/client-logs` | Medium | Low | Rate limiting already exists (50/IP/60s). Add client-side dedup (don't send same error twice within 5s). |

---

## 10. Appendix: File Manifest

### New files

```
src/ainrf/
├── api/
│   ├── middleware/
│   │   ├── exception_handler.py          # P0-3: Global exception handler
│   │   └── rate_limit.py                 # P2-5: Per-user rate limiter
│   └── routes/
│       └── sla_metrics.py                # P1-1: SLA metric definitions
├── telemetry/
│   ├── __init__.py                       # P1-4: OTel SDK initialization
│   ├── config.py                         # P1-4: OTel configuration from env
│   └── middleware.py                      # P1-4: OTel-FastAPI integration

frontend/src/
├── shared/
│   └── utils/
│       └── reportWebVitals.ts            # P2-2: Web Vitals collection

deploy/
├── config/
│   ├── loki/
│   │   └── loki-config.yml               # P2-1: Loki configuration
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources/
│       │   │   └── loki.yml              # P2-1: Loki datasource
│       │   └── alerting/
│       │       └── contact-points.yml    # P2-3: Grafana Alerting config
│       └── dashboards/
│           └── ainrf/
│               └── ainrf-overview.json   # Updated: SLA + frontend panels

docs/
└── proposals/
    └── observability-enhancement.md      # This document
```

### Modified files

| File | P0 | P1 | P2 |
|------|:--:|:--:|:--:|
| `src/ainrf/api/routes/metrics.py` | ✓ (rewrite) | — | — |
| `src/ainrf/observability/litefuse_reporter.py` | ✓ | — | — |
| `src/ainrf/observability/protocol.py` | ✓ | — | — |
| `src/ainrf/api/middleware/request_context.py` | ✓ | ✓ | — |
| `src/ainrf/api/middleware/request_logging.py` | — | ✓ | — |
| `src/ainrf/api/middleware/__init__.py` | — | ✓ | ✓ |
| `src/ainrf/api/app.py` | ✓ | ✓ | ✓ |
| `src/ainrf/api/errors.py` | ✓ | — | — |
| `src/ainrf/api/routes/health.py` | — | ✓ | — |
| `src/ainrf/api/schemas.py` | — | ✓ | — |
| `src/ainrf/security/audit.py` | — | ✓ | — |
| `src/ainrf/db/instrumentation.py` | ✓ | ✓ | ✓ |
| `src/ainrf/agentic_researcher/service.py` | — | ✓ | ✓ |
| `src/ainrf/logging.py` | — | ✓ | — |
| `src/ainrf/api/routes/client_logs.py` | — | ✓ | ✓ |
| `pyproject.toml` | ✓ | ✓ | — |
| `deploy/docker-compose.yml` | — | — | ✓ |
| `deploy/docker-compose.observability.yml` | — | — | ✓ |
| `deploy/config/prometheus.yml` | — | — | ✓ |
| `deploy/config/prometheus/rules/ainrf-alerts.yml` | — | ✓ | ✓ |
| `deploy/config/grafana/dashboards/ainrf/ainrf-overview.json` | — | ✓ | ✓ |
| `deploy/config/grafana/provisioning/datasources/prometheus.yml` | — | ✓ | — |
| `frontend/src/components/common/ErrorBoundary.tsx` | — | — | ✓ |
| `frontend/src/shared/utils/errorBoundary.tsx` | — | — | ✓ |
| `frontend/src/App.tsx` | — | — | ✓ |
