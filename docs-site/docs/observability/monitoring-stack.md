---
title: 监控栈
description: Prometheus、Grafana 与 Gatus 监控栈部署架构、预置 Dashboard、主动探测、告警规则与配置文件结构。
---

OpenScience 的 Docker 部署自带完整的 Prometheus、Grafana 与 Gatus 监控栈，无需额外安装。

## 组件

| 组件 | 镜像 | 说明 |
|------|------|------|
| Prometheus | `prom/prometheus:v3.3.1` | 抓取应用与 Gatus 指标，30 天数据保留 |
| Grafana | `grafana/grafana:11.6.1` | 自动配置数据源和预置 Dashboard |
| Gatus | `twinproduction/gatus:v5.36.0` | 主动探测 production、staging 和可选 development，提供公开状态页 |

## 部署架构

```text
Browser -> :8192/grafana -> Grafana 127.0.0.1:3000
                              |
                              v
                     Prometheus 127.0.0.1:9091
                              |
                              v
                    Backend 127.0.0.1:18000/metrics

Browser -> :8192/uptime -> Gatus 127.0.0.1:8080
                              |-> production /api/health
                              |-> staging /api/health
                              `-> optional development /api/health
```

### 网络模式

| 部署方式 | Prometheus 抓取目标 | Grafana 访问方式 |
|---------|--------------------|--------------------|
| `docker-compose.yml`（Bridge 网络） | `ainrf:8000/metrics` | nginx `/grafana` 反代 |
| `docker-compose.cpu.yml`（Host 网络） | `127.0.0.1:18000/metrics` | `http://<宿主机IP>:8192/grafana` |
| `docker-compose.gpu.yml`（Bridge 网络） | `ainrf:8000/metrics` | `http://<宿主机IP>:8192/grafana` |

## 启用方式

三种 Docker Compose 文件均已内置，无需额外配置：

```bash
# 基础版（nginx + TLS）
cd deploy && docker compose up -d --build

# CPU-only（host 网络）
cd deploy && docker compose -f docker-compose.cpu.yml up -d --build

# GPU 版
cd deploy && docker compose -f docker-compose.gpu.yml up -d --build
```

| 部署方式 | Grafana 访问地址 | 默认账号 |
|---------|-----------------|---------|
| 基础版（nginx） | `https://<host>/grafana` | OpenScience auth proxy |
| CPU-only | `http://<host>:8192/grafana` | OpenScience auth proxy |
| GPU 版 | `http://<host>:8192/grafana` | OpenScience auth proxy |

CPU-only production 的 `3000`（Grafana）与 `9091`（Prometheus）只监听 loopback；staging
对应为 `2300` 与 `9092`，同样只监听 loopback。日常浏览器访问统一经 nginx 的认证路径，
避免绕过 OpenScience session 边界。

Gatus 本身同样只监听 production loopback `127.0.0.1:8080`，由 nginx 通过公开的
`/uptime/` 前缀提供状态页。OpenScience 的 `/api/*` 和 `/assets/*` 仍由原服务处理；
nginx 将 Gatus 的绝对资源与 API 地址限制改写到 `/uptime/*`，避免路由冲突。Gatus 固定
使用 v5.36.0；升级时必须重新执行子路径 smoke，因为上游尚未原生支持 base path。
状态页通过 Gatus `ui.custom-css` 使用 OpenScience 标记、配色、字体、间距、圆角和卡片层级。
所有 endpoint 都隐藏 URL、hostname 和错误详情，避免公开内部拓扑或失败响应。

每个环境按稳定 `component` 标签拆成独立探针：

| 组件 | 探测契约 |
|------|----------|
| Web App | 从 nginx 用户入口请求 `/`，要求 200 且页面包含 `OpenScience` 标记 |
| Backend API | 请求 `/api/health`，要求整体状态 `ok` |
| Database / Filesystem | 复用 `/api/health`，分别检查对应 `checks.*.status == ok` |
| Runtime | 复用 `/api/health`，允许可解释的 `degraded`，拒绝 `unhealthy` |
| SSH | 复用 `/api/health` 的 `container_health.ssh_ok`；仅在对应环境启用 runtime reconciliation 时开启 |
| Task Execution / Worker | 通过 Prometheus HTTP query API 检查 API scrape heartbeat、domain telemetry scrape、最老可执行或待对账 Turn submission 小于 300 秒及 risk state 已知 |
| Prometheus | 请求直接服务的 `/-/ready`（带当前 route prefix） |
| Grafana | 请求直接服务的 `/api/health`（带当前 subpath）并检查数据库状态 |

production 与 staging 默认启用核心和监控探针；staging SSH 默认关闭。worktree development
端口是派生值且默认没有 Prometheus/Grafana，因此 `GATUS_DEVELOPMENT_ENABLED`、
`GATUS_DEVELOPMENT_MONITORING_ENABLED`、`GATUS_DEVELOPMENT_WORKER_ENABLED` 和 SSH 开关均需
指向稳定实例后显式启用。

OpenScience 在 `http(s)://<host>/status/` 提供内置状态页，直接消费上述
`/uptime/api/v1/endpoints/statuses`、单 endpoint 的 `statuses` 与 `uptimes/{duration}`
API，按 Production 组件展示整体状态、30 天 uptime 条带、响应时间、事件日历与历史事件，
支持明暗主题与中英文切换；外部实现同样可读取这些 API 构建自定义状态页。公网
`/uptime/metrics` 明确返回 404；Prometheus 仍通过 loopback 上的 Gatus 原生 `/metrics` 抓取。

:::caution
默认密码 `ainrf-grafana` 仅用于初次登录。生产环境请在 `.env` 中设置 `GRAFANA_ADMIN_PASSWORD` 为强密码。
:::

## 预置 Dashboard

Dashboard JSON 位于 `deploy/config/grafana/dashboards/ainrf/ainrf-overview.json`，自动加载。默认刷新 30 秒，时间范围最近 1 小时。

| 面板 | 类型 | 指标 | 说明 |
|------|------|------|------|
| HTTP 请求速率 | 时序图 | `ainrf_http_requests_total` | 按 method/path/status 的请求速率 |
| HTTP 错误率 | Stat | 5xx/total | 5xx 错误占比，阈值 1%/5% |
| P95 延迟 | Stat | `ainrf_http_request_duration_seconds` | 95 分位延迟，阈值 1s/5s |
| 请求延迟分布 | 时序图 | p50/p90/p99 | 延迟分布趋势 |
| 登录成功/失败 | 时序图 | `ainrf_auth_login_*_total` | 登录成功/失败趋势 |
| 终端命令执行 | 时序图 | `ainrf_terminal_exec_*` | 允许/拒绝的终端命令 |
| 活跃 WebSocket 会话 | Stat | `ainrf_terminal_ws_active` | 当前活跃 WS 连接数 |
| 敏感文件访问 | 柱状图 | `ainrf_files_sensitive_path_access_total` | 敏感路径访问事件 |
| 环境更新 | 时序图 | `ainrf_environment_update_total` | 环境检测/更新操作 |
| 代码会话创建 | Stat | `ainrf_code_session_created_total` | 最近 1 小时代码会话数 |
| HTTP contract traffic | 时序图 | `ainrf_http_contract_requests_total` | 按 canonical/root/`v1`/external-compatible 与 stable operation 展示长期流量 |
| HTTP contract errors | 时序图 | `ainrf_http_contract_requests_total` | 按 surface/operation 展示 4xx/5xx |
| Telemetry guard | Stat | unmatched + delivery latch | unknown 分类或 durable delivery failure 时保持 fail-closed |

## 配置文件结构

```
deploy/config/
├── gatus.yaml                 # uptime 探测、状态页与 SQLite 保留配置
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

## 告警规则

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

架构清理使用的临时 Grafana cleanup panel、`ainrf_cleanup_*` / `ainrf_deprecated_*` 查询和 Release E 专用告警已经删除。当前 Dashboard 与规则只消费长期指标；正式长期配置/CLI alias 不建立 removal 告警。

### 启用告警通知

预置规则仅定义了告警条件，未配置通知渠道。在 Grafana 中添加：

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

## 相关文档

- [可观测性概览](/observability/) — 审计事件与日志架构
- [Prometheus 指标](/observability/metrics) — 指标参考与 PromQL 查询
- [部署概览](/deployment/) — 部署方式选择
