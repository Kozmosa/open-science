---
title: Prometheus 指标
description: OpenScience Prometheus 指标参考 — 计数器、直方图、仪表盘与 PromQL 查询示例。
---

通过 `AINRF_METRICS_ENABLED=true` 启用，端点：`GET /metrics`。

## 计数器（Counters）

| 指标 | 标签 | 说明 |
|------|------|------|
| `ainrf_http_requests_total` | method, path, status | HTTP 请求总数 |
| `ainrf_http_contract_requests_total` | surface, operation, method, status_class | 长期 HTTP contract 流量；准确区分 canonical、root、`/v1` 与 external-compatible |
| `ainrf_auth_login_success_total` | — | 登录成功次数 |
| `ainrf_auth_login_failed_total` | reason | 按原因分类的登录失败次数 |
| `ainrf_terminal_exec_total` | environment_id | 终端命令执行次数 |
| `ainrf_terminal_exec_denied_total` | — | 被拒绝的终端命令次数 |
| `ainrf_code_session_created_total` | — | Code-Server 会话创建次数 |
| `ainrf_files_sensitive_path_access_total` | pattern | 敏感路径访问次数 |
| `ainrf_environment_update_total` | — | 环境更新次数 |

## 直方图（Histograms）

| 指标 | 说明 |
|------|------|
| `ainrf_http_request_duration_seconds` | 请求延迟分布 |
| `ainrf_http_contract_request_duration_seconds` | 按稳定 surface、operation 与 method 的长期请求延迟 |

## 仪表盘（Gauges）

| 指标 | 说明 |
|------|------|
| `ainrf_terminal_ws_active` | 当前活跃的终端 WebSocket 连接数 |
| `ainrf_http_contract_telemetry_delivery_failure_latched` | durable evidence 写入失败锁存；非零时 compatibility removal 必须 fail-closed |

## PromQL 查询示例

```promql
# 登录失败速率（每秒，5 分钟窗口）
rate(ainrf_auth_login_failed_total[5m])

# 99 分位请求延迟
histogram_quantile(0.99, rate(ainrf_http_request_duration_seconds_bucket[5m]))

# 活跃终端会话数
ainrf_terminal_ws_active

# 按模式的敏感文件访问
sum by (pattern) (rate(ainrf_files_sensitive_path_access_total[1h]))

# HTTP 请求速率（按状态码）
sum by (status) (rate(ainrf_http_requests_total[5m]))

# 长期 compatibility route 观察（removal authority）
sum by (surface, operation) (increase(ainrf_http_contract_requests_total[30d]))

# 登录成功率
rate(ainrf_auth_login_success_total[5m])
/
(rate(ainrf_auth_login_success_total[5m]) + rate(ainrf_auth_login_failed_total[5m]))
```

HTTP contract durable evidence 按日期、surface、operation、method、status class 聚合写入 state root 下的 `runtime/compatibility_telemetry.sqlite3`，保留 180 天并跨 backend 重启连续。Prometheus process counter 可重置，但 release removal evidence 不依赖单进程值。

架构清理期间使用的 `ainrf_cleanup_*` 与 superseded `ainrf_deprecated_*` 指标已删除。正式配置/CLI alias 不属于待删除债务；route compatibility 只使用上述长期、低基数 contract 指标，不再维护平行的临时统计。

2026-08-01 的不可变 release staging 验收确认：正式请求产生 `ainrf_http_contract_*`，已删除 route 以 `surface="non_product"`、`operation="unmatched"`、`status_class="4xx"` 归类；API 重启后 durable aggregate 继续存在，而 process-local Prometheus counter 按设计重新开始。指标 exposition 中不存在 `ainrf_cleanup_*` 或 `ainrf_deprecated_*`。

## 相关文档

- [可观测性概览](/observability/) — 审计事件目录
- [监控栈](/observability/monitoring-stack) — Grafana Dashboard 与告警
- [安全架构](/security/) — 安全配置参考
