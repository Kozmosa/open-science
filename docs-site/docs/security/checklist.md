---
title: 生产检查清单
description: OpenScience 生产部署安全检查项与安全事件响应流程。
---

## 部署前检查清单

- [ ] 设置 `AINRF_PRODUCTION=true`
- [ ] 配置 `AINRF_ALLOWED_CIDRS` 为实际网络范围
- [ ] 设置 `AINRF_TRUSTED_PROXY_CIDRS` 为反向代理 IP
- [ ] 禁用公开注册：`AINRF_PUBLIC_REGISTRATION_ENABLED=false`
- [ ] 在反向代理（Caddy/Nginx）后运行并启用 TLS
- [ ] 仅绑定 `127.0.0.1` — 永远不要直接暴露后端
- [ ] 生成强随机 API key：`openssl rand -hex 32`
- [ ] 设置适当的 `AINRF_LOGIN_MAX_FAILURES` 和锁定时长
- [ ] 启用指标采集：`AINRF_METRICS_ENABLED=true`
- [ ] 配置 `<state_root>/logs/` 的日志轮转

## 维护窗口发布检查

- [ ] L1 已通过，release manifest 记录当前 Git SHA 和四个镜像的 image ID。
- [ ] Release staging 使用同一 manifest、独立凭据和独立数据，smoke 通过。
- [ ] 人工完成本次改动涉及的核心页面和业务流程验收。
- [ ] 发布前完成完整备份，并实际验证备份能够恢复。
- [ ] API、Web、worker 和监控镜像来自同一 release manifest，production 使用 `--no-build`。
- [ ] 记录发布结果；失败时恢复上一份 manifest 和发布前备份。

## 日志位置

| 类型 | 路径 |
|------|------|
| 应用日志 | `<state_root>/logs/backend-YYYYMMDD.log` |
| 审计事件 | 同一文件，按 `component=audit` 过滤 |
| 反向代理日志 | Nginx/Caddy 的标准日志 |

## 安全事件响应

排查安全事件时，搜索审计日志：

```bash
# 所有认证事件
grep '"component":"audit"' logs/backend-*.log | grep '"event":"auth.'

# 敏感文件访问
grep '"event":"files.sensitive_path_access"' logs/backend-*.log

# 终端会话
grep '"event":"terminal.' logs/backend-*.log

# SSH 配置变更
grep '"event":"environment.ssh_field_changed"' logs/backend-*.log

# 所有 high/critical 级别事件
grep '"severity":"high\|"severity":"critical"' logs/backend-*.log
```

通过 `request_id` 字段关联事件 — 它将同一次 HTTP 请求或 WebSocket 会话内的所有日志行串联起来。

## 相关文档

- [安全架构](/security/) — 三层防御与配置参考
- [审计日志](/observability/audit-logs) — 完整审计事件目录
- [Prometheus 指标](/observability/metrics) — 安全相关指标
