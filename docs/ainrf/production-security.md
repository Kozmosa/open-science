---
title: 生产安全
---

# 生产安全

## 安全架构

AINRF 采用三层纵深防御架构：

1. **IP 白名单** — 在请求到达应用前拒绝未知网络来源。通过 `AINRF_ALLOWED_CIDRS` 配置。
2. **请求大小限制** — 阻断超大载荷。默认 50 MB，通过 `AINRF_MAX_REQUEST_BODY_BYTES` 配置。
3. **JWT 认证** — 所有非豁免路由均需有效 JWT token。生产模式下豁免范围更严格。

## 配置参考

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AINRF_PRODUCTION` | `false` | 启用生产模式 |
| `AINRF_ALLOWED_CIDRS` | _(空)_ | 允许连接的 CIDR 列表（逗号分隔） |
| `AINRF_TRUSTED_PROXY_CIDRS` | _(空)_ | 受信反向代理的 CIDR |
| `AINRF_PUBLIC_REGISTRATION_ENABLED` | `true` | 是否允许公开注册 |
| `AINRF_LOGIN_MAX_FAILURES` | `10` | 锁定前的登录失败次数 |
| `AINRF_LOGIN_LOCKOUT_HOURS` | `24` | 锁定时长（小时） |
| `AINRF_MAX_REQUEST_BODY_BYTES` | `52428800` | 请求体上限（50 MB） |
| `AINRF_MAX_CONCURRENT_REQUESTS` | `0` | 最大并发请求数（0 = 无限） |
| `AINRF_METRICS_ENABLED` | `false` | 启用 Prometheus `/metrics` 端点 |

## 生产部署检查清单

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

## 日志位置

- **应用日志**：`<state_root>/logs/backend-YYYYMMDD.log`
- **审计事件**：同一文件，按 `component=audit` 过滤
- **Nginx/Caddy 访问日志**：反向代理的标准日志

## 审计事件

完整审计事件目录见 [[observability]]。

## 敏感路径检测

以下路径模式会触发级别为 `high` 的 `files.sensitive_path_access` 审计事件：

| 模式 | 示例 |
|---|---|
| `.env` 文件 | `.env`、`.env.production` |
| 证书文件 | `*.pem`、`*.key` |
| SSH 密钥 | `id_rsa`、`id_ed25519`、`authorized_keys` |
| 数据库文件 | `*.sqlite`、`*.db` |
| 系统文件 | `/etc/passwd`、`/etc/shadow` |
| SSH 目录 | `~/.ssh/*` |
| 特权路径 | `/root/*`、`/proc/*` |
| 管理员密钥 | `admin_initial_password.txt` |

## 受信代理配置

在反向代理后运行时，`X-Forwarded-For` 头让应用看到真实客户端 IP。但必须显式配置以防止 IP 伪造：

```
# 仅信任本地反向代理
AINRF_TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

不设置 `AINRF_TRUSTED_PROXY_CIDRS` 时，应用信任来自任何来源的 `X-Forwarded-For`（开发模式行为）。

## Token 安全

- 访问令牌为短有效期 JWT
- 刷新令牌允许免重新认证续期
- **两者都不会被记录** — 脱敏层从所有日志输出中剥离 `Authorization` 头、`api_key` 参数和 `token` 查询字符串
- 审计日志仅记录认证发生的事实，永远不记录凭据本身

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
