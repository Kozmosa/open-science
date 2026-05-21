---
aliases: [CLI Reference, 命令行参考, cli]
tags: [ainrf, cli]
---

# CLI 命令参考

所有命令通过 `uv run ainrf <command>` 执行。添加 `--help` 查看完整参数。

## onboard

初始化本地状态目录 (`~/.ainrf`)、默认配置和工作区。

```bash
uv run ainrf onboard
```

## serve

启动后端 API 服务（FastAPI + Uvicorn）。

```bash
uv run ainrf serve
uv run ainrf serve --host 0.0.0.0 --port 8000
uv run ainrf serve --state-root ~/.ainrf
```

参数：
- `--host`：监听地址（默认 `127.0.0.1`）
- `--port`：监听端口（默认 `8000`）
- `--state-root`：状态存储目录（默认 `~/.ainrf`）

以 daemon 模式启动时写入 PID 文件 (`~/.ainrf/runtime/ainrf-api.pid`) 供 `stop` 命令使用。

## stop

停止由 `serve` 启动的后台 daemon 进程。

```bash
uv run ainrf stop
```

## login

通过 CLI 登录并缓存 JWT access token（交互式提示输入用户名和密码）。

```bash
uv run ainrf login
uv run ainrf login --server http://127.0.0.1:8000
```

## container

管理可复用的容器/环境配置 profile。

```bash
uv run ainrf container add
```

## 关联笔记

- [[quickstart]] — 首次使用流程
- [[webui]] — 浏览器访问方式
