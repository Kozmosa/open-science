---
doc_state: historical
status: implemented
last_reviewed: 2026-08-01
review_by: 2026-08-31
---

# HTTP Adapter 依赖方向闭合设计

> [!warning] Historical specification
> 本设计已于 2026-08-01 完整实现并归档。当前 contract 以 PROJECT_BASIS.md、docs-site/docs/architecture.md、产品代码和正常 L0/L1 guard 为准。

**Status:** Implemented and archived
**Date:** 2026-08-01
**Scope:** `ainrf.command`、`ainrf.api.cli`、`ainrf.api.server`、FastAPI application composition、uvicorn/daemon/reload 入口和永久 import-direction gate
**Depends on:** [`2026-07-29-openscience-architecture-cleanup-refactor-design.md`](2026-07-29-openscience-architecture-cleanup-refactor-design.md)

## 1. 问题与证据

`PROJECT_BASIS.md` 要求产品 import graph 无 cycle，且 non-API Module 不得通过直接、惰性、动态 import 或字符串入口反向依赖 `ainrf.api`。当前 `src/ainrf/server.py` 仍执行：

```python
module = importlib.import_module("ainrf.api.app")
```

该调用由 2026-07-29 的依赖方向清理引入，用于替换静态 `from ainrf.api import create_app`。当时 cleanup-only guard 只解析 Python import AST，因此静态 edge 与 allowlist 归零，但语义依赖没有消失。P6 后临时 guard 按计划删除，正常 L1 当前也没有永久 owner。

这不是 runtime cycle 的已知故障，而是架构约束与实现不一致：通用 server Module 仍知道 FastAPI Adapter 的具体模块名，动态 import 只是降低了可见性，没有增加 Depth 或 Locality。

## 2. 决策

1. FastAPI application construction、HTTP process composition、uvicorn lifecycle 和 reload factory 由 `ainrf.api` HTTP Adapter 拥有。
2. 通用 CLI command composition 不 import、lazy import 或动态加载 `ainrf.api`。
3. 不使用 uvicorn import string、entry-point string 或 subprocess module string 规避依赖检查；字符串中出现产品模块名同样属于依赖。
4. daemon PID、process group、健康等待等不依赖 HTTP schema 的能力可以保留为中立 process Module，但必须通过注入的命令或健康 probe Interface 工作。
5. 增加正常 L0/L1 长期 guard；不恢复 cleanup-only snapshot 或全量 public-interface digest。

## 3. 目标 Module 与 Seam

建议结构：

```text
ainrf.command
  └── build_base_cli()                    # 非 HTTP 命令

ainrf.api.cli                             # HTTP Adapter composition root
  ├── 注册 serve 命令
  ├── 组合 build_base_cli()
  └── 调用 ainrf.api.server

ainrf.api.server
  ├── create_http_app(config)
  ├── create_development_app()
  ├── run_http_server(...)
  └── 提供明确的 uvicorn factory

ainrf.process                             # 可选中立 Module
  ├── spawn_daemon(command, ...)
  ├── stop_daemon(pid_file)
  └── wait_until_healthy(probe, ...)
```

`ainrf.api.cli` 是 HTTP Adapter 的 composition root，不是 application Module。它可以依赖通用 command builder 和 application Interfaces；反向依赖不允许。

## 4. Interface 要求

### 4.1 HTTP server Interface

公开表面保持最小：

```text
create_http_app(config) -> FastAPI
create_development_app() -> FastAPI
run_http_server(host, port, state_root, workers)
```

FastAPI、uvicorn 参数和 middleware lifecycle 不泄露到 Domain/runtime Module。

### 4.2 Process Interface

若拆出中立 process Module，其 Interface 只接受：

- argv；
- PID/log 路径；
- timeout；
- 注入的 async health probe。

它不知道 `/api/health`、FastAPI factory 或 `ainrf.api` 模块路径。

## 5. 永久验证

新增静态检查覆盖：

- `Import` / `ImportFrom`；
- `importlib.import_module()` 的字符串字面量；
- `__import__()` 字面量；
- uvicorn factory/import strings；
- subprocess argv 中的 `ainrf.api` 模块入口；
- product import cycles。

允许的方向是 HTTP/CLI/worker Adapter 调用 application Interface；禁止 Domain、DB、runtime、execution、Literature、Harness 和中立 process Module 依赖 HTTP Adapter。

测试必须进入正常 L0/L1 owner，不使用即将删除的临时 allowlist。若确需 composition entrypoint allowlist，条目必须是明确的 `ainrf.api.*` owner，不能允许 non-API source。

## 6. 迁移顺序

1. 为现有 `serve`、daemon、reload 和 health wait 行为补正式 Interface tests。
2. 建立能捕获当前动态 import 的 failing guard。
3. 将 HTTP construction 和 uvicorn lifecycle 移入 `ainrf.api`。
4. 将 CLI 改为由 HTTP Adapter composition root 注册 `serve`；保持 `openscience`、`ainrf` 命令名称不变。
5. 如有必要，将通用 daemon/process 能力下沉中立 Module。
6. 更新 Docker、staging reload、开发脚本、README 与 tests。
7. 删除 `src/ainrf/server.py` 或将其收窄为不含 HTTP 知识的中立 process Module。

## 7. 验收条件

- 产品源码中不存在 non-API → `ainrf.api` 的静态、惰性、动态或字符串依赖。
- 产品 import graph 无 cycle。
- `openscience serve` 前台/daemon 行为不变。
- staging uvicorn reload、production image command 和 `/api/health` readiness contract 通过。
- `tests/test_server.py` 改为通过正式 HTTP/process Interface 测试，不 patch 私有动态 loader。
- L0/L1 永久执行 dependency-direction guard。
- 不操作 production；验证使用确定性测试和隔离开发/发布环境。

## 8. 非目标

- 不重构 FastAPI routes 或 Pydantic schemas。
- 不改变认证、middleware 顺序或 HTTP prefix。
- 不顺手重写整个 Typer CLI。
- 不通过新增抽象 port 隐藏单一实现；只有 HTTP Adapter 与可复用 process lifecycle 之间形成真实 Seam。
