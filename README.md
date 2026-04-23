# AINRF

`scholar-agent` 当前的核心是 `ainrf` 前后端产品面，而不是调研笔记本身。

仓库当前主要包含两类内容：

- `src/ainrf/` + `frontend/`：AINRF 的 CLI、后端 API、WebUI 与相关 runtime 能力。
- `docs/` + `ref-repos/`：用于设计参考、历史追溯和产品决策输入的知识资产。

## 当前重点

AINRF 当前已经落地的主表面包括：

- 可安装的 `ainrf` CLI
- `ainrf serve` 后端 API
- `scripts/webui.sh` 驱动的 WebUI 前后端联调入口
- environment 管理、terminal、tasks 与 workspace browser

研究笔记、外部项目调研与历史 RFC 仍然保留，但默认不再作为仓库主入口。

## 目录

- `src/ainrf/`: Python package、CLI、API 与 runtime
- `frontend/`: React + Vite WebUI
- `tests/`: Python tests
- `scripts/`: 本地开发、联调与 docs 构建辅助脚本
- `docs/`: AINRF 产品文档、参考知识库与历史材料
- `ref-repos/`: 只读参考仓库

## 常用命令

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf --help
UV_CACHE_DIR=/tmp/uv-cache uv run ainrf serve --help
scripts/webui.sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/
cd frontend && npm run lint && npm run test:run && npm run build
```

## 文档入口

- AINRF 当前使用文档：`docs/ainrf/index.md`
- 仓库长期约束：`PROJECT_BASIS.md`
- 研究/历史材料：`docs/framework/`、`docs/projects/`、`docs/summary/`
