---
title: 部署概览
description: OpenScience 生产部署前置条件、首次登录、安全检查清单、故障排查与环境变量参考。
---

从零将 OpenScience 部署到生产环境或实验室服务器的完整指南。覆盖裸机（systemd）和容器（Docker Compose）两种主要部署方式。

| 部署方式 | 说明 |
| --- | --- |
| [裸机部署](/deployment/bare-metal) | 一键脚本安装到 Ubuntu/Debian，systemd 管理服务。 |
| [Docker Compose](/deployment/docker) | 标准版、GPU 版、CPU-only 版三种容器部署方案。 |
| [Kubernetes](/deployment/kubernetes) | 生产集群 K8s 部署，含 Ingress 和 NetworkPolicy。 |

## 前置条件

| 项目 | 最低要求 |
|------|---------|
| OS | Ubuntu 22.04+ / Debian 12+ |
| Python | 3.13+ |
| Node.js | 20+（仅构建前端时需要） |
| 内存 | 2 GB+ |
| 磁盘 | 10 GB+（含 state 目录） |
| 网络 | 服务器可访问目标 SSH 环境 |

## 首次登录

部署完成后，访问 `https://<your-server>/`：

1. 使用部署脚本生成的 admin 密码登录（首次启动时写入 `<state_root>/admin_initial_password.txt`）
2. 进入 Settings → Admin 面板创建普通用户
3. 禁用 public registration（如果还没通过环境变量禁用）

## 安全检查清单

- [ ] `AINRF_PRODUCTION=1` 已设置（禁用 /docs, /openapi.json, /redoc）
- [ ] `AINRF_ALLOWED_CIDRS` 已限制到实际网络范围
- [ ] `AINRF_PUBLIC_REGISTRATION_ENABLED=false`（私有部署）
- [ ] 后端只监听 `127.0.0.1:8000`（不直接暴露）
- [ ] Nginx/Caddy 前置 TLS
- [ ] `AINRF_TRUSTED_PROXY_CIDRS` 已设置（防止 IP 伪造）
- [ ] API key 和 JWT secret 使用强随机值
- [ ] 登录暴力破解保护已启用（默认 10 次失败锁定 24 小时）
- [ ] 日志文件轮转已配置

:::tip
详细安全架构参考 [安全架构](/security/) 和 [生产检查清单](/security/checklist)。
:::

## 反向代理配置

除了自带的 Nginx 配置，也可以使用 Caddy（自动 HTTPS）：

```bash
# Caddy 配置模板见 deploy/examples/Caddyfile.example
```

## 日志与监控

### 日志位置

| 日志 | 路径 |
|------|------|
| 后端应用日志 | `<state_root>/logs/backend-YYYYMMDD.log` |
| Nginx 访问日志 | `/var/log/nginx/access.log` |
| systemd 日志 | `journalctl -u ainrf -f` |

### Prometheus 指标

设置 `AINRF_METRICS_ENABLED=true` 后，指标暴露在 `/metrics`。

### Docker 部署监控栈

Docker Compose 部署自带 Prometheus、Grafana 和 Gatus 监控栈。Gatus 状态页通过
`/uptime/` 公开，主动探测 production、staging 和可选的固定 development 实例。
详见 [监控栈](/observability/monitoring-stack)。

## 三种环境各自负责什么

| 环境 | 用途 | 是否可变 |
| --- | --- | --- |
| 本地开发 | 快速修改、单元测试、前后端联调 | 是 |
| Staging | 遥测观察、集成验证、问题复现 | 是，支持热重载 |
| Release staging | 运行与生产发布相同的 API/Web 镜像，供人工验收 | 否，不重新构建 |

推荐流程：

```text
L1 → 构建一次 release → release staging smoke + 人工验收
   → 安排维护窗口 → 完整备份并验证恢复 → production 部署
   → smoke；失败时恢复备份和上一份 manifest
```

Release staging 不会自动操作生产环境，也不负责替代人工判断。发布 manifest 记录 Git SHA、
四个镜像引用及其本地 image ID；release staging 和 production 启动前都会核对这些记录。

## 常用运维命令

```bash
# 查看服务状态
sudo systemctl status ainrf

# 查看实时日志
sudo journalctl -u ainrf -f

# 重启服务
sudo systemctl restart ainrf

# 更新部署
cd /opt/ainrf-src && git pull
sudo bash deploy/deploy.sh

# Docker 更新
cd deploy && docker compose up -d --build
```

## 环境变量完整参考

见 `deploy/examples/ainrf.env.example`，每个变量都有注释说明、默认值和示例。

## 故障排查

| 症状 | 检查 |
|------|------|
| 502 Bad Gateway | `systemctl status ainrf` — 后端是否运行 |
| 403 Forbidden | 检查 Nginx `geo` 块和 `AINRF_ALLOWED_CIDRS` |
| 登录返回 403 | `AINRF_PUBLIC_REGISTRATION_ENABLED` 是否为 false |
| WebSocket 断连 | Nginx `proxy_read_timeout` 需 ≥ 86400s |
| 日志文件过大 | 配置 logrotate 轮转 `<state_root>/logs/*.log` |
