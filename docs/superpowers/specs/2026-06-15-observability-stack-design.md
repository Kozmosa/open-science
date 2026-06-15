# AINRF 可观测性栈设计

日期：2026-06-15
状态：已实现（Phase 0–2，3 commits）

## 概述

AINRF 生产环境具备三层可观测性：指标（Prometheus + prometheus_client）、追踪（OpenTelemetry + Litefuse）、日志（structlog + Loki）。三层各自负责不同粒度的观测需求，通过共享 `request_id` / `trace_id` 实现跨层关联。

## 架构总览

```
┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐
│   Frontend    │   │   Backend     │   │   Infrastructure         │
│               │   │               │   │                          │
│ ErrorBoundary │   │ OTel Auto-    │   │ Prometheus (metrics)     │
│  → /client-   │   │ Instrumentation│   │ Grafana (dashboards)    │
│    logs       │   │  ├─ FastAPI    │   │ Litefuse (LLM traces)   │
│               │   │  ├─ SQLite3    │   │ Loki (log aggregation)  │
│ Web Vitals    │   │  └─ HTTPX      │   │                          │
│  → /client-   │   │               │   │                          │
│    metrics    │   │ prometheus_    │   │                          │
│               │   │ client SDK     │   │                          │
│               │   │  → /metrics    │   │                          │
│               │   │               │   │                          │
│               │   │ structlog      │   │                          │
│               │   │  → stdout +    │   │                          │
│               │   │    file        │   │                          │
│               │   │               │   │                          │
│               │   │ LitefuseReporter│  │                          │
│               │   │  → Litefuse    │   │                          │
│               │   │    backend     │   │                          │
│               │   │               │   │                          │
│               │   │ SLA Metrics    │   │                          │
│               │   │  → Prometheus  │   │                          │
└──────────────┘   └──────────────┘   └──────────────────────────┘
```

## 一、指标层（Prometheus）

### 库

使用 `prometheus_client`（v0.22+），替代了初版手写 in-memory dicts + 自渲染的临时实现。主要在 `src/ainrf/api/routes/metrics.py`。

### 指标命名

所有 AINRF 指标统一使用 `ainrf_` 前缀。指标分为四类：

| 类别 | 示例 | 数量 |
|------|------|------|
| HTTP | `ainrf_http_requests_total`（Counter，labels: method/path/status）、`ainrf_http_request_duration_seconds`（Histogram） | 2 |
| 认证 | `ainrf_auth_login_success_total`、`ainrf_auth_login_failed_total`（labels: reason） | 2 |
| 任务 | `ainrf_task_created_total`、`ainrf_task_completed_total`、`ainrf_task_failed_total` | 3 |
| SSH | `ainrf_ssh_connection_attempt_total`、`ainrf_ssh_connection_error_total`（labels: host/error_type）、`ainrf_ssh_command_duration_seconds` | 3 |
| 终端 | `ainrf_terminal_exec_total`、`ainrf_terminal_exec_denied_total`、`ainrf_terminal_ws_active`（Gauge） | 3 |
| 数据库 | `ainrf_db_query_duration_seconds`、`ainrf_db_slow_query_total` | 2 |
| 文件 | `ainrf_files_sensitive_path_access_total` | 1 |
| 环境 | `ainrf_environment_update_total`、`ainrf_code_session_created_total` | 2 |
| 客户端 | `ainrf_client_error_events_total` | 1 |

### SLA 指标

新增独立模块 `src/ainrf/api/routes/sla_metrics.py`：

- `ainrf_sla_task_completion_seconds`（Histogram，buckets: 1min–2h）— 任务端到端延迟
- `ainrf_sla_llm_first_token_seconds`（Histogram，buckets: 0.1s–60s）— LLM 首 token 延迟
- `ainrf_sla_tasks_total`（Counter，labels: status/researcher_type/harness_engine）— 按结果分类的任务计数
- `ainrf_sla_uptime_seconds`（Gauge）— 进程存活时间
- `ainrf_rate_limited_total`（Counter，labels: reason/path）— 速率限制拒绝计数

### 废弃

`set_gauge` 从未有外部调用方，已移除。

## 二、追踪层（OpenTelemetry + Litefuse）

### OpenTelemetry（自动插桩）

`src/ainrf/telemetry/` 包提供零配置自动插桩。默认关闭（`AINRF_OTEL_ENABLED=false`），开启后自动为以下三类调用创建 span：

- **FastAPIInstrumentor** — 所有 HTTP 请求（排除 `/health`、`/metrics`）
- **SQLite3Instrumentor** — 所有数据库查询
- **HTTPXInstrumentor** — 所有出站 HTTP 调用

配置方式（环境变量）：

- `AINRF_OTEL_ENABLED` — 设为 `true` 启用
- `AINRF_OTEL_EXPORTER_ENDPOINT` — OTLP 导出端点（不设则仅本地记录）
- `AINRF_OTEL_SAMPLE_RATE` — 采样率（默认 1.0）
- `AINRF_OTEL_DEPLOYMENT_ENV` — 部署环境标签（默认 `production`）

OTel 的设计意图是**仅用于自动插桩**，不替代 Prometheus 指标或 Litefuse LLM 追踪。三者各司其职。

### Litefuse（LLM 专属追踪）

`src/ainrf/observability/` 包提供抽象的 `ObservabilityReporter` 协议和 Litefuse（Langfuse fork）具体实现。延迟加载 `langfuse` SDK，缺失时优雅降级为 `NullReporter`（空操作）。

Trace 层级结构：

```
start_trace(trace_id)         → trace-type observation（根节点）
  ├─ record_generation(tid)   → generation-type observation（嵌套在 trace 下）
  └─ record_span(tid)         → span-type observation（嵌套在 trace 下）
end_trace(trace_id)           → 关闭根 trace context manager
```

`SafeReporter` 外套确保 observability 后端的任何异常都不会传播到主应用逻辑。

### 分布式 trace 传播

`request_context.py` 中间件同时支持：

- **X-Request-ID** — 读取上游 header → 存在则沿用，不存在则生成 UUID v4
- **W3C traceparent** — 解析 `version-trace_id-parent_id-flags`，提取 `trace_id`

两者均绑定到 structlog contextvars，并通过响应 header 回传。

## 三、日志层（structlog + Loki + 审计）

### structlog

全局 JSON 格式结构化日志，配置在 `src/ainrf/logging.py`：

- 输出：同时写文件（`<state_root>/logs/backend-YYYYMMDD.log`，50MB 轮转，保留 10 个备份）和 stdout（供 Docker 采集）
- 上下文传播：通过 `structlog.contextvars` 注入 `request_id` 和 `task_id`
- 中间件链：`request_context` → `request_logging` → `exception_handler`
- 异常处理：最内层中间件捕获 unhandled exception → 返回 `{error_code, message, request_id}` JSON

### Loki 日志聚合

Docker Compose 新增 `loki` 服务（`grafana/loki:3.5.0`）：

- 配置：`deploy/config/loki/loki-config.yml`（30 天保留，TSDB 存储，单节点模式）
- Grafana 已预配 Loki 数据源（`deploy/config/grafana/provisioning/datasources/loki.yml`）
- 容器继续使用 `json-file` driver；后续可按需挂载 `promtail` 或切换 `loki-docker-driver`

### 审计日志

`src/ainrf/security/audit.py` 提供两种 API：

```python
# 推荐：类型约束的新 API
from ainrf.security.audit import AuditEvent, emit_audit
emit_audit(AuditEvent(action="user.login", result="success", actor_id="user-123"))

# 兼容：自由形式的旧 API（deprecated，保留向后兼容）
from ainrf.security.audit import audit_event
audit_event("user.login", severity="info", username="user-123")
```

`AuditEvent` dataclass 字段：`action`、`result`、`actor_id`、`actor_type`、`resource_id`、`resource_type`、`details`、`severity`、`client_ip`、`request_id`（自动从 structlog contextvars 提取）。

## 四、健康检查

`GET /health` 返回分组件状态探测：

```json
{
  "status": "ok",
  "uptime_seconds": 35.9,
  "checks": {
    "database":   {"status": "ok", "latency_ms": 0.2, "error": null},
    "litefuse":   {"status": "ok", "latency_ms": 0.0, "error": null},
    "filesystem": {"status": "ok", "latency_ms": 0.1, "error": null},
    "runtime":    {"status": "degraded", ...}
  }
}
```

只有 `unhealthy` 组件会拉低整体 `status` 为 `degraded`。运行时二进制不可用（测试环境常有）仅记录为 advisory。

## 五、告警系统

Prometheus 告警规则位于 `deploy/config/prometheus/rules/ainrf-alerts.yml`，共 14 条活跃规则，按 9 个组划分：

| 组 | 规则数 | 覆盖 |
|----|--------|------|
| `ainrf.http` | 2 | 5xx 错误率（critical）、P95 延迟（warning） |
| `ainrf.tasks` | 1 | 任务失败尖峰（warning） |
| `ainrf.ssh` | 1 | SSH 连接错误（warning） |
| `ainrf.db` | 1 | 慢查询尖峰（warning） |
| `ainrf.sla` | 4 | 任务 P95 > 30min（critical）、LLM 首 token P99 > 10s（warning）、错误预算燃烧率（critical）、速率限制检测（warning） |
| `ainrf.auth` | 2 | 登录失败率（warning）、账户锁定（info） |
| `ainrf.terminal` | 1 | 命令执行拒绝（warning） |
| `ainrf.security` | 1 | 敏感文件访问（high） |
| `ainrf.system` | 1 | 高请求率（warning） |

## 六、前端遥测

### Error Boundary

`ErrorBoundary.componentDidCatch` 通过 `logError()` 上报到 `POST /api/client-logs`（有缓冲 + `sendBeacon` 发送）。

### Web Vitals

`frontend/src/shared/utils/reportWebVitals.ts` 使用 `PerformanceObserver` API 收集四大核心指标：

| 指标 | 观测类型 | Good 阈值 | Poor 阈值 |
|------|----------|-----------|-----------|
| LCP | `largest-contentful-paint` | ≤ 2500ms | > 4000ms |
| FCP | `paint` (first-contentful-paint) | ≤ 1800ms | > 3000ms |
| INP | `event` | ≤ 200ms | > 500ms |
| CLS | `layout-shift` | ≤ 0.1 | > 0.25 |

后端端点 `POST /api/client-metrics` 将这些记录为 Prometheus 直方图（`ainrf_client_lcp_seconds` 等）。

## 七、速率限制

### 全 API 速率限制

`src/ainrf/api/middleware/rate_limit.py` — 滑窗 token bucket 中间件：

- 默认关闭（`AINRF_RATE_LIMIT_ENABLED=true` 启用）
- 按键：已认证用户 ID / 客户端 IP
- 配置：`AINRF_RATE_LIMIT_REQUESTS_PER_MINUTE`（默认 60）、`AINRF_RATE_LIMIT_BURST_SIZE`（默认 10）
- 返回：429 + `Retry-After: 60` + `{error_code: "RATE_LIMITED", ...}`
- 5 分钟过期清理防止内存增长

### 其他限制点

- `build_concurrency_limit_middleware`（全局并发量，返回 503）— 已加 `ainrf_rate_limited_total{reason="concurrency"}` 指标
- `POST /client-logs`（IP 速率限制，返回 429）— 已加 `ainrf_rate_limited_total{reason="ip_quota"}` 指标

## 八、守护与仪表盘

### Grafana

- 预配仪表盘：`deploy/config/grafana/dashboards/ainrf/ainrf-overview.json`（AINRF Overview，14 个面板）
- 数据源：Prometheus（默认）、Loki（日志聚合）
- 认证：通过 nginx auth_request 代理
- 入口：`/grafana`

### Prometheus

- v3.3.1，每 15 秒抓取 `/metrics`
- 30 天 / 2GB 留存
- 入口（认证）：`/prometheus`

## 九、依赖项

```
# pyproject.toml — 可观测性相关
prometheus-client>=0.22.0
structlog>=25.4.0
langfuse>=2.0.0
opentelemetry-api>=1.30.0
opentelemetry-sdk>=1.30.0
opentelemetry-instrumentation-fastapi>=0.51b0
opentelemetry-instrumentation-sqlite3>=0.51b0
opentelemetry-instrumentation-httpx>=0.51b0
opentelemetry-exporter-otlp-proto-http>=1.30.0
```

## 十、环境变量速查

| 变量 | 默认值 | 作用 |
|------|--------|------|
| `AINRF_METRICS_ENABLED` | `false` | 启用 `/metrics` 端点 |
| `AINRF_OBSERVABILITY_ENABLED` | `false` | 启用 Litefuse LLM 追踪 |
| `AINRF_OBSERVABILITY_BASE_URL` | — | Litefuse 后端 URL |
| `AINRF_OBSERVABILITY_SECRET_KEY` | — | Litefuse API 密钥 |
| `AINRF_OBSERVABILITY_PUBLIC_KEY` | — | Litefuse API 公钥 |
| `AINRF_OTEL_ENABLED` | `false` | 启用 OTel 自动插桩 |
| `AINRF_OTEL_EXPORTER_ENDPOINT` | — | OTLP exporter 端点 |
| `AINRF_OTEL_SAMPLE_RATE` | `1.0` | 追踪采样率 |
| `AINRF_OTEL_DEPLOYMENT_ENV` | `production` | 部署环境标签 |
| `AINRF_RATE_LIMIT_ENABLED` | `false` | 启用全 API 速率限制 |
| `AINRF_RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | 每分钟最大请求数 |
| `AINRF_RATE_LIMIT_BURST_SIZE` | `10` | token bucket 突发容量 |

## 实现历史

- **Phase 0**（`6ed8d04`）：prometheus_client 迁移、Litefuse trace 修复、全局异常处理、上游 trace context、QueryTimer SQL 修复
- **Phase 1**（`5fa7644`）：SLA 指标、增强健康检查、结构化审计日志、OTel 自动插桩、速率限制仪表化
- **Phase 2**（`84217c3`）：Loki 日志聚合、前端遥测、告警扩展（14 条规则）、全 API 速率限制、QueryTimer 废弃标识
