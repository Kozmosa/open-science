---
title: Docker Compose 部署
description: 标准版（Nginx+TLS）、GPU 实验室版、CPU-only 版三种 Docker Compose 部署方案。
---

适用于没有 systemd 的容器环境。提供三种 Compose 文件覆盖不同场景。

## 方式 A：标准版（Nginx + TLS）

使用 `docker-compose.yml`，包含 Nginx 反向代理和 TLS。

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

多阶段构建自动完成：前端 Node 构建 → Python 包安装 → Claude Code + Codex CLI → 精简运行时镜像。可通过 `--build-arg CLAUDE_CODE_VERSION=2.1.167` 锁定版本。

### 4. 常用操作

```bash
docker compose logs -f ainrf       # 查看日志
docker compose restart ainrf       # 重启后端
docker compose down                # 停止服务
docker compose up -d --build       # 更新代码后重建
```

:::note
OpenScience 容器仅 expose 8000 端口给 Nginx 容器，不直接对外。Nginx 容器处理 TLS、IP allowlist、静态文件和 WebSocket 反向代理。
:::

---

## 方式 B：GPU 实验室版

适用于：没有 root 权限但能创建 Docker 容器、需要 GPU 透传的实验室机器。使用 `docker-compose.gpu.yml`，无需 Nginx/TLS，直接暴露 HTTP。

### 1. 生成密钥

```bash
# JWT 密钥
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# API Key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# 保存好这个值，这就是你的 API key

# API Key 哈希（写入 compose 文件）
python3 -c "from hashlib import sha256; print(sha256(b'上一步的API_KEY').hexdigest())"
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

:::caution
此模式不使用 TLS，仅适用于内网/VPN 环境。如需公网暴露，在前面加一层 Nginx 反向代理。
:::

:::note
GPU 透传要求宿主机已安装 NVIDIA 驱动和 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)。可用 `docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi` 验证。
:::

---

## 方式 C：CPU-only 版

适用于：不需要 GPU、宿主机未装 NVIDIA 驱动的服务器。使用 `docker-compose.cpu.yml`，与 GPU 版相同但无 GPU 设备透传。

这是正式 production 路径。密钥生成步骤与 GPU 版相同，然后：

```bash
# 在 deploy/.env 或受控环境中准备 production secrets
# 一次构建 Web、API 和监控配置镜像，再部署同一 release manifest
bash deploy/release-production.sh
# 获取 admin 密码
docker compose -f deploy/docker-compose.cpu.yml exec ainrf \
  cat /opt/ainrf/state/admin_initial_password.txt
# 查看日志
docker compose -f deploy/docker-compose.cpu.yml logs -f ainrf
```

访问 `http://<机器IP>:8192/`。

Production Compose 不执行源码构建，也不挂载 Git checkout、worktree、`src/ainrf`
或宿主机 `frontend/dist`。API 和所有 Python worker 使用同一个 API 镜像；WebUI 与
nginx 配置位于配套 web 镜像中。构建脚本会先完成全部镜像，再写出包含 release ID
及四个镜像引用的 manifest，随后 Compose 只使用这些预构建镜像启动。

保留上一份 manifest 作为代码回滚单位。OpenScience 默认采用实验室计划维护窗口发布，
允许约 2–3 小时停机：发布前完成 state、workspace 与 tenant 数据的完整备份和隔离恢复验证，
停止 writer 后部署同一 manifest，执行必要迁移和只读 smoke；失败时按 runbook 人工恢复数据
并启动上一份 manifest。独立 release staging 是可选强化，不是默认门禁；如未来接入 registry，
production 仍应使用已经构建的同一组镜像引用，而不是在主机上重新生成另一套字节。

当前 `deploy/release-production.sh` 尚未自动执行数据备份、隔离恢复验证或数据 rollback；它只负责
构建同版本制品、部署和健康检查。在维护窗口自动化补齐前，操作员必须先按受控 runbook 手工
完成备份与恢复验证，不能把该脚本的成功输出视为完整 L4 验收。

### Release staging 人工验收

先用 `build-production.sh` 生成 release manifest，再用仓库外、权限为 `0600` 的
staging 独立配置启动相同的 API/Web 镜像：

```bash
export OPENSCIENCE_RELEASE_MANIFEST=/secure/releases/<sha>.env
export OPENSCIENCE_RELEASE_STAGING_ENV_FILE=/secure/releases/staging.env
bash deploy/release-staging.sh up
bash deploy/release-staging.sh smoke
```

浏览器入口为 `http://127.0.0.1:7192/`。完成登录、核心页面和本次变更的人工验收后，
用 `down` 停止；只有明确确认时才用 `purge` 删除其一次性数据。这个环境不会执行生产
迁移、切换或回滚，也不会把自动 smoke 当作人工验收结论。

---

## 监控栈

三种 Docker Compose 文件均已内置 Prometheus、Grafana 与 Gatus，详见 [监控栈](/observability/monitoring-stack)。

公开 uptime 状态页统一由 nginx 暴露在 `http(s)://<host>/uptime/`。Gatus 将 production、
staging 和可选 development 拆成 Web、API、Database、Filesystem、Runtime、SSH、Worker、
Prometheus 与 Grafana 组件探针。开发环境的 monitoring/worker/SSH 探针使用独立开关；所有
公开卡片隐藏内部 URL、hostname 和错误信息，且 `/uptime/metrics` 不对公网开放。

| 部署方式 | Grafana 地址 | 默认账号 |
|---------|-------------|---------|
| 标准版（nginx） | `https://<host>/grafana` | OpenScience auth proxy |
| CPU-only（host 网络） | `http://<host>:8192/grafana` | OpenScience auth proxy |
| GPU 版 | `http://<host>:8192/grafana` | OpenScience auth proxy |

CPU-only 的后端 `18000`、Prometheus `9091`、Grafana `3000` 和 Gatus `8080` 默认只监听
`127.0.0.1`；外部浏览器只使用 `8192`。staging 使用不重叠的 loopback 端口
`7192/17000/9092/2300`，因此可以与 production 同时运行。

## 相关文档

- [部署概览](/deployment/) — 前置条件与安全检查清单
- [Kubernetes](/deployment/kubernetes) — 生产集群部署
- [可观测性概览](/observability/) — 监控与审计
