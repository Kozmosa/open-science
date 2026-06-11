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

## Monitoring Stack (Prometheus + Grafana)

AINRF 的 Docker 部署自带完整的监控栈：

| 组件 | 镜像 | 说明 |
|------|------|------|
| Prometheus | `prom/prometheus:v3.3.1` | 抓取 `/metrics`，30 天数据保留 |
| Grafana | `grafana/grafana:11.6.1` | 自动配置数据源和预置 Dashboard |

### 部署架构

```
┌──────────────┐    scrape     ┌──────────────┐    query    ┌──────────────┐
│   AINRF      │ ◄──────────── │  Prometheus  │ ◄─────────  │   Grafana    │
│  :8192/metrics│   15s interval│   :9090      │             │   :3000      │
└──────────────┘               └──────────────┘             └──────────────┘
```

- **Bridge 网络**（`docker-compose.yml`、`docker-compose.gpu.yml`）：Prometheus 抓取 `ainrf:8000/metrics`，Grafana 通过 nginx `/monitoring/` 反代访问
- **Host 网络**（`docker-compose.cpu.yml`）：所有组件共享宿主机网络，Prometheus 抓取 `localhost:8192/metrics`，Grafana 直接访问 `http://<宿主机IP>:3000/`

### 启用方式

三种 Docker Compose 文件均已内置 Prometheus + Grafana，无需额外配置：

```bash
# Base (nginx + TLS)
cd deploy && docker compose up -d --build

# CPU-only (host network)
cd deploy && docker compose -f docker-compose.cpu.yml up -d --build

# GPU
cd deploy && docker compose -f docker-compose.gpu.yml up -d --build
```

启动后：

| 部署方式 | Grafana 访问地址 | 默认账号 |
|---------|-----------------|---------|
| Base (nginx) | `https://<host>/monitoring/` | `admin` / `ainrf-grafana` |
| CPU (host network) | `http://<host>:3000/` | `admin` / `ainrf-grafana` |
| GPU | `http://<host>:3000/` | `admin` / `ainrf-grafana` |

> [!warning]
> 默认密码 `ainrf-grafana` 仅用于初次登录。生产环境请在 `.env` 中设置 `GRAFANA_ADMIN_PASSWORD` 为强密码。

### 预置 Dashboard

Dashboard JSON 位于 `deploy/config/grafana/dashboards/ainrf/ainrf-overview.json`，Grafana 启动时自动加载。面板：

| 面板 | 类型 | 指标 | 说明 |
|------|------|------|------|
| HTTP Request Rate | 时序图 | `ainrf_http_requests_total` | 按 method/path/status 的请求速率 |
| HTTP Error Rate | Stat | 5xx/total | 5xx 错误占比，阈值 1%/5% |
| P95 Latency | Stat | `ainrf_http_request_duration_seconds` | 95 分位延迟，阈值 1s/5s |
| Request Duration Histogram | 时序图 | p50/p90/p99 | 延迟分布趋势 |
| Login Success / Failure | 时序图 | `ainrf_auth_login_*_total` | 登录成功/失败趋势 |
| Terminal Exec Commands | 时序图 | `ainrf_terminal_exec_*` | 允许/拒绝的终端命令 |
| Active WebSocket Sessions | Stat | `ainrf_terminal_ws_active` | 当前活跃 WS 连接数 |
| Sensitive File Access | 柱状图 | `ainrf_files_sensitive_path_access_total` | 敏感路径访问事件 |
| Environment Updates | 时序图 | `ainrf_environment_update_total` | 环境检测/更新操作 |
| Code Sessions Created | Stat | `ainrf_code_session_created_total` | 最近 1 小时代码会话数 |

Dashboard 默认刷新间隔 30 秒，时间范围最近 1 小时。

### 配置文件结构

```
deploy/config/
├── prometheus.yml              # Bridge 网络抓取配置
├── prometheus-host.yml         # Host 网络抓取配置
├── prometheus-rules.yml        # 告警规则（→ symlink 到 examples/）
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   ├── prometheus.yml      # Bridge 网络数据源
    │   │   └── prometheus-host.yml # Host 网络数据源
    │   └── dashboards/
    │       └── ainrf.yml           # Dashboard 自动加载
    └── dashboards/
        └── ainrf/
            └── ainrf-overview.json  # 主 Dashboard
```

## Alert Rules

告警规则模板在 `deploy/examples/prometheus-rules.example.yml`，已自动挂载到 Prometheus 容器。

### 预置告警

| 告警名 | 条件 | 级别 | 说明 |
|--------|------|------|------|
| `AINRFHighLoginFailureRate` | 登录失败 > 2/s 持续 1min | warning | 疑似暴力破解 |
| `AINRFAccountLockouts` | 账户锁定 > 0.1/s 持续 2min | info | 用户被频繁锁定 |
| `AINRFTerminalExecDenials` | 命令拒绝 > 1/s 持续 1min | warning | 策略违规 |
| `AINRFSensitiveFileAccess` | 敏感路径访问 > 0.5/s 持续 1min | high | 疑似越权访问 |
| `AINRFHighRequestRate` | 总请求 > 100/s 持续 2min | warning | 流量异常 |
| `AINRFHighErrorRate` | 5xx 占比 > 10% 持续 2min | critical | 后端异常 |

### 启用告警通知

预置规则仅定义了告警条件，未配置通知渠道。在 Grafana 中添加通知：

1. 进入 Grafana → Alerting → Contact points
2. 添加通知渠道（Webhook / 邮件 / 钉钉 / 飞书等）
3. 在 Notification policies 中绑定告警标签到对应渠道

或直接在 Prometheus 侧配置 `alertmanager`：

```yaml
# alertmanager.yml
route:
  receiver: "ainrf-team"
receivers:
  - name: "ainrf-team"
    webhook_configs:
      - url: "https://your-webhook-url"
```

### 自定义告警

编辑 `deploy/examples/prometheus-rules.example.yml`，按需调整阈值和新增规则。修改后重启 Prometheus：

```bash
docker compose restart prometheus
```