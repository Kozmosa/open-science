# OpenScience WebUI

`frontend/` 是 OpenScience 的 React + Vite WebUI。本文只提供子系统导航；
长期项目规则以 [`../PROJECT_BASIS.md`](../PROJECT_BASIS.md) 为最高
authority，当前产品架构与 HTTP contract 见
[`../docs-site/docs/architecture.md`](../docs-site/docs/architecture.md)。

修改前端实现、测试或浏览器行为前，还必须阅读
[`../.rules/frontend-and-testing.md`](../.rules/frontend-and-testing.md)。涉及
DevTools、部署、loaded asset 或 session-scoped config 排障时，先阅读
[`../dev-bitter-lesson.md`](../dev-bitter-lesson.md)。

## 结构边界

- 依赖方向固定为 `app -> features -> shared/design-system`。
- Page 只负责 composition；feature adapter 把 generated transport 映射为
  view model，页面不直接消费 raw payload。
- 共用布局优先使用 `src/components/layout/` 中的 `PageShell`、
  `SplitPane`、`SectionStack` 与 `CardGrid`。
- Tailwind class 必须静态可发现；不要动态拼接 class 名，也不要嵌套
  `@dnd-kit` draggable wrapper。
- `src/generated/transport/` 由 FastAPI/Pydantic OpenAPI 生成，按
  [`src/generated/transport/README.md`](src/generated/transport/README.md)
  操作，禁止手工修改。

## 常用命令

从仓库根目录使用 `--prefix`，避免依赖 shell 当前目录：

```bash
npm --prefix frontend run check:transport
npm --prefix frontend run lint
npm --prefix frontend run test:run
npm --prefix frontend run build
```

不要从仓库根目录运行 `npx tsc`、`tsc --noEmit` 或独立的 `tsc -b`；
`npm --prefix frontend run build` 才是受支持的 TypeScript project-reference
构建入口。

## 联调与验证

标准 full-profile 本地环境由仓库脚本管理：

```bash
bash scripts/dev.sh up --profile full
bash scripts/dev.sh smoke --profile full
bash scripts/dev.sh doctor --profile full --browser
```

涉及 DOM、computed style、Network、focus 或加载资源的结论必须使用通过
doctor preflight 的 Chrome DevTools 验证。`VITE_USE_MOCK=true` 只提供离线
MSW 合同场景，不能作为真实 API、worker、tenant 权限或持久化证据。
