# AINRF WebUI

`frontend/` 是 AINRF 的 React + Vite WebUI，而不是默认模板工程。

当前前端主要负责：

- 与后端同源联调的 WebUI 壳层
- environment 管理与选择
- personal terminal / managed task terminal 控制面
- workspace browser / code-server 面板
- 与 `scripts/webui.sh` 配合的一键启动开发流程

## 常用命令

```bash
npm install
npm run dev
npm run preview
npm run lint
npm run test:run
npm run build
```

## 联调方式

推荐从仓库根目录使用：

```bash
scripts/webui.sh
scripts/webui.sh dev
scripts/webui.sh preview
```

这个入口会同时启动：

- `uv run ainrf serve`
- Vite dev server 或 preview server

并自动处理本地 `./.ainrf/` 状态目录、WebUI service key 与同源代理头注入。

## 边界

- 前端默认通过同源代理访问 `/api`、`/code` 与 `/terminal`。
- 浏览器端不应直接持有或手动注入服务端 API key。
- 产品 contract 以仓库根目录 `docs/ainrf/index.md`、`src/ainrf/README.md` 与当前测试为准。
