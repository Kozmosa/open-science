---
aliases:
  - AINRF 使用文档
  - AINRF Usage Guide
tags:
  - ainrf
  - cli
  - docs
  - obsidian-note
source_repo: scholar-agent
source_path: docs/ainrf/index.md
last_local_commit: workspace aggregate
---
# AINRF 使用文档

> [!abstract]
> 本页记录当前仓库里已经存在并应作为默认主入口理解的 AINRF 产品面：CLI、后端 API、WebUI，以及围绕 environment / terminal / task / workspace browser 的运行时能力。文档站点构建与研究笔记预览仍然保留，但它们属于辅助维护流程，而不是仓库中心。

## AINRF 是什么

AINRF 是 `scholar-agent` 当前的核心前后端产品，实现面主要包括：

- `src/ainrf/` 提供的可安装 CLI 与后端 API
- `frontend/` 提供的 WebUI
- `scripts/webui.sh` 驱动的前后端联合启动入口
- environment 管理、keepalive personal terminal、managed task terminal 与受管 workspace browser

研究笔记、外部项目调研和历史 RFC 仍保留在仓库中，但主要服务于设计参考和历史追溯。

## 快速开始

建议先确认 CLI 与主入口可见：

```bash
uv run ainrf --version
uv run ainrf --help
scripts/webui.sh
```

如果你的目标是直接使用当前产品面，优先顺序是：

1. `scripts/webui.sh`
2. `uv run ainrf serve`
3. `uv run ainrf onboard`

## WebUI 一键启动

当前推荐入口：

```bash
scripts/webui.sh
scripts/webui.sh dev
scripts/webui.sh preview
scripts/webui.sh dev --backend-public
scripts/webui.sh preview --backend-public
```

这个入口会自动处理：

- 默认 `UV_CACHE_DIR=/tmp/uv-cache`
- 本地 `./.ainrf/` 状态目录
- `./.ainrf/webui.env` 中的 WebUI service key 生成或复用
- `./.ainrf/config.json` 的 `api_key_hashes` 补齐
- 后端 `ainrf serve` 与前端 dev/preview server 的联合启动

默认暴露策略是：

- 前端对内网可见：`0.0.0.0`
- 后端默认仅本机：`127.0.0.1`

浏览器通过前端同源代理访问 `/api`、`/code` 与 `/terminal`，不再需要手动管理浏览器侧 API key。

## 启动 AINRF 服务

当前底层后端入口是：

```bash
uv run ainrf serve
uv run ainrf serve --help
```

这条路径主要适合：

- 单独联调后端 API
- 配合自定义前端或代理层调试
- 验证 CLI / daemon / runtime 行为

对大多数产品使用场景，仍应优先回到 `scripts/webui.sh`。

## 首次初始化

当前初始化入口是：

```bash
uv run ainrf onboard
```

它会准备服务运行所需的本地状态与配置。若 `serve` 提示缺少必要配置，应先完成 onboarding，而不是把缺失配置视为 notes/tooling 问题。

## 其他 CLI 命令

除初始化与服务启动外，当前还能直接看到的命令入口包括：

```bash
uv run ainrf container add
uv run ainrf container add --help
```

它们用于写入 environment / container 相关配置项，是产品 runtime 的配置型入口。

## 文档与知识库维护入口

以下命令仍然保留，但应理解为维护辅助流程，而非 AINRF 主产品面：

```bash
scripts/serve.sh
scripts/build.sh
uv run python scripts/build_html_notes.py serve
uv run python scripts/build_html_notes.py build
```

它们主要服务于 `docs/` 知识库与历史材料的本地预览/构建。

## 常用开发与验证命令

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

前端常用验证入口：

```bash
cd frontend && npm run lint
cd frontend && npm run test:run
cd frontend && npm run build
```

## 说明与边界

- 本页优先描述当前已经交付的 AINRF 产品表面。
- `docs/` 和 `ref-repos/` 为产品设计输入与历史追溯提供支持，但不再作为仓库默认主线。
- 历史 RFC、路线图和更大运行时愿景，不应直接表述为当前已经交付的能力。

## 关联笔记

- [[index]]
- [[framework/index]]
- [[framework/ai-native-research-framework]]
