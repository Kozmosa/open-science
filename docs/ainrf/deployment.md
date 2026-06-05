---
aliases: [生产部署, Deployment Guide]
tags: [ainrf, deploy, production]
source_repo: scholar-agent
---

# 生产部署指南

> [!abstract]
> 从零将 AINRF 部署到生产环境或实验室服务器的完整步骤。
> 覆盖裸机（systemd）和容器（Docker Compose）两种部署方式。

## 前置条件

| 项目 | 最低要求 |
|------|---------|
| OS | Ubuntu 22.04+ / Debian 12+ |
| Python | 3.13+ |
| Node.js | 20+（仅构建前端时需要） |
| 内存 | 2 GB+ |
| 磁盘 | 10 GB+（含 state 目录） |
| 网络 | 服务器可访问目标 SSH 环境 |

## 方式一：裸机部署（推荐实验室环境）

### 1. 克隆仓库并安装

```bash
git clone https://github.com/your-org/scholar-agent.git /opt/ainrf-src
cd /opt/ainrf-src
```

### 2. 一键部署

```bash
sudo bash deploy/deploy.sh --install-dir /opt/ainrf --state-dir /var/lib/ainrf
```

脚本会自动完成：

1. 创建 `ainrf` 系统用户
2. 用 `uv` 安装 Python 包到 `/opt/ainrf`
3. 构建前端并拷贝到 `/opt/ainrf/frontend/dist`
4. 生成 JWT secret 和 API key
5. 安装 Nginx 反向代理配置
6. 生成自签名 TLS 证书（实验室用）
7. 安装 systemd service 并启动

> [!warning]
> 部署脚本输出的 API key **只显示一次**，务必保存。

### 3. 调整 Nginx 访问控制

编辑 `/etc/nginx/sites-available/ainrf`，将 `geo` 块中的 CIDR 改为你的实际网络：

```nginx
geo $allowed_client {
    default         0;
    10.0.0.0/8     1;     # 替换为你的实验室子网
    127.0.0.1      1;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 4. 配置环境变量

编辑 systemd override 或直接修改 `/etc/systemd/system/ainrf.service`：

```ini
Environment=AINRF_PRODUCTION=1
Environment=AINRF_ALLOWED_CIDRS=10.0.0.0/8
Environment=AINRF_PUBLIC_REGISTRATION_ENABLED=false
Environment=AINRF_METRICS_ENABLED=true
Environment=AINRF_TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

完整环境变量参考见 `deploy/examples/ainrf.env.example`。

### 5. 重启生效

```bash
sudo systemctl daemon-reload
sudo systemctl restart ainrf
```

## 方式二：Docker Compose 部署

适用于没有 systemd 的容器环境。

### 1. 准备配置

```bash
cp deploy/.env.example deploy/.env
vim deploy/.env  # 填入 JWT_SECRET 和 API_KEY_HASHES
```

### 2. 生成 TLS 证书

```bash
# 实验室自签名（测试用）
bash deploy/tls/generate-self-signed.sh

# 生产环境使用真实证书
cp /path/to/cert.pem deploy/tls/cert.pem
cp /path/to/key.pem  deploy/tls/key.pem
```

### 3. 构建并启动

```bash
cd deploy
docker compose up -d --build
```

多阶段构建自动完成：前端 Node 构建 → Python 包安装 → 精简运行时镜像（无 Node/uv/git）。

### 4. 常用操作

```bash
docker compose logs -f ainrf       # 查看日志
docker compose restart ainrf       # 重启后端
docker compose down                # 停止服务
docker compose up -d --build       # 更新代码后重建
```

> [!note]
> AINRF 容器仅 expose 8000 端口给 Nginx 容器，不直接对外。
> Nginx 容器处理 TLS、IP allowlist、静态文件和 WebSocket 反向代理。


## 方式二 B：GPU 实验室（无 root、Docker only）

适用于：没有 root 权限但能创建 Docker 容器、需要 GPU 透传的实验室机器。
使用专用 compose 文件 `docker-compose.gpu.yml`，无需 Nginx/TLS，直接暴露 HTTP。

### 1. 生成密钥

```bash
# JWT 密钥
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# → 复制输出

# API Key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# → 复制输出，这就是你的 API key，保存好

# API Key 哈希（写入 compose 文件）
python3 -c "from hashlib import sha256; print(sha256(b'上一步的API_KEY').hexdigest())"
# → 复制输出
```

### 2. 编辑 compose 文件

```bash
vim deploy/docker-compose.gpu.yml
# 把两个 <CHANGE_ME> 替换为上面生成的值
```

### 3. 构建并启动

```bash
cd deploy
docker compose -f docker-compose.gpu.yml up -d --build
```

### 4. 获取 admin 密码

```bash
docker compose -f docker-compose.gpu.yml exec ainrf \
  cat /opt/ainrf/state/admin_initial_password.txt
```

### 5. 访问

浏览器打开 `http://<机器IP>:8192/`，用 admin 密码登录。

### 常用操作

```bash
docker compose -f docker-compose.gpu.yml logs -f ainrf   # 查看日志
docker compose -f docker-compose.gpu.yml restart ainrf   # 重启
docker compose -f docker-compose.gpu.yml down             # 停止
docker compose -f docker-compose.gpu.yml up -d --build   # 更新代码后重建
```

> [!warning]
> 此模式不使用 TLS，仅适用于内网/VPN 环境。
> 如需公网暴露，在前面加一层 Nginx 反向代理。

> [!note]
> GPU 透传要求宿主机已安装 NVIDIA 驱动和 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。
> 可用 `docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi` 验证。

## 方式三：Kubernetes 部署

适用于生产集群环境。所有 manifest 在 `deploy/k8s/` 下。

### 1. 构建并推送镜像

```bash
docker build -f deploy/Dockerfile -t registry.example.com/ainrf:v1.0.0 .
docker push registry.example.com/ainrf:v1.0.0
```

### 2. 创建 Secrets

```bash
kubectl create secret generic ainrf-secrets \
  --namespace ainrf \
  --from-literal=JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  --from-literal=API_KEY_HASHES="$(python3 -c "from hashlib import sha256; print(sha256(b'YOUR_API_KEY').hexdigest())")"

kubectl create secret tls ainrf-tls \
  --namespace ainrf \
  --cert=deploy/tls/cert.pem --key=deploy/tls/key.pem
```

### 3. 一键部署

```bash
bash deploy/k8s/deploy.sh --image registry.example.com/ainrf:v1.0.0
```

### 4. 更新镜像

```bash
bash deploy/k8s/deploy.sh --image registry.example.com/ainrf:v1.1.0
```

### 5. 卸载

```bash
bash deploy/k8s/deploy.sh --destroy
```

### K8s 资源清单

| 文件 | 资源 | 说明 |
|------|------|------|
| `namespace.yaml` | Namespace | `ainrf` 命名空间 |
| `pvc.yaml` | PVC | 状态存储 10Gi + 工作区 20Gi |
| `secrets.yaml` | Secret | JWT 密钥和 API key 哈希 |
| `tls-secret.yaml` | Secret | TLS 证书 |
| `deployment.yaml` | Deployment | 后端 Pod（非 root，资源限制 2Gi） |
| `service.yaml` | Service | ClusterIP:8000 |
| `ingress.yaml` | Ingress | Nginx Ingress + TLS + WebSocket |
| `networkpolicy.yaml` | NetworkPolicy | 仅允许 Ingress 访问后端 |

## 首次登录

部署完成后，访问 `https://<your-server>/`。

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

> [!tip]
> 详细安全架构参考 [[production-security]]。

## 日志与监控

### 日志位置

| 日志 | 路径 |
|------|------|
| 后端应用日志 | `<state_root>/logs/backend-YYYYMMDD.log` |
| Nginx 访问日志 | `/var/log/nginx/access.log` |
| systemd 日志 | `journalctl -u ainrf -f` |

### Prometheus 指标

设置 `AINRF_METRICS_ENABLED=true` 后，指标暴露在 `/metrics`（需认证）。

示例告警规则见 `deploy/examples/prometheus-rules.example.yml`。

> [!tip]
> 完整指标和审计事件参考 [[observability]]。

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

## 反向代理配置

除了自带的 Nginx 配置，也可以使用 Caddy（自动 HTTPS）：

```bash
# Caddy 配置模板见 deploy/examples/Caddyfile.example
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
