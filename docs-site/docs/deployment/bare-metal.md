---
title: 裸机部署
description: 使用一键脚本将 OpenScience 部署到 Ubuntu/Debian 裸机服务器，systemd 管理服务。
---

适用于实验室环境，使用 systemd 管理服务。

## 1. 克隆仓库并安装

```bash
git clone https://github.com/your-org/open-science.git /opt/ainrf-src
cd /opt/ainrf-src
```

## 2. 一键部署

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

:::caution
部署脚本输出的 API key **只显示一次**，务必保存。
:::

## 3. 调整 Nginx 访问控制

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

## 4. 配置环境变量

编辑 systemd override 或直接修改 `/etc/systemd/system/ainrf.service`：

```ini
Environment=AINRF_PRODUCTION=1
Environment=AINRF_ALLOWED_CIDRS=10.0.0.0/8
Environment=AINRF_PUBLIC_REGISTRATION_ENABLED=false
Environment=AINRF_METRICS_ENABLED=true
Environment=AINRF_TRUSTED_PROXY_CIDRS=127.0.0.1/32
```

完整环境变量参考见 `deploy/examples/ainrf.env.example`。

## 5. 重启生效

```bash
sudo systemctl daemon-reload
sudo systemctl restart ainrf
```

## 常用运维

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
```

## 相关文档

- [部署概览](/deployment/) — 前置条件与安全检查清单
- [Docker Compose](/deployment/docker) — 容器化部署
- [安全架构](/security/) — 安全配置详解
