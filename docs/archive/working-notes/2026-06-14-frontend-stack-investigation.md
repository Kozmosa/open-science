# AINRF 前端技术栈与实现状况调研报告

> 调研范围：`frontend/` 目录（React + Vite 单页应用）。
> 调研方式：源码结构、依赖清单、配置、路由、组件分层、状态管理、数据层与测试覆盖。
> 说明：受限于当前环境无图像/截图分析能力，本报告基于代码层面进行结构化分析，未做视觉截图验证。

---

## 1. 整体技术栈

| 层级 | 技术选型 | 版本 / 备注 |
|------|----------|-------------|
| 框架 | React | `^19.2.4`，函数组件 + Hooks |
| 构建工具 | Vite | `^8.0.4`，开发/预览服务器、HMR、代理 |
| 路由 | `react-router-dom` | `^7.14.0`，BrowserRouter |
| 状态管理（服务端） | `@tanstack/react-query` | `^5.96.2`，负责服务端状态、缓存、轮询 |
| 样式 | Tailwind CSS v4 | `^4.2.2`，通过 `@tailwindcss/vite` 插件引入，无传统 `tailwind.config.js` |
| 类型 | TypeScript | `~6.0.2`，项目引用 (`tsconfig.app.json` / `tsconfig.node.json`) |
| 图标 | `lucide-react` | `^1.7.0` |
| 国际化 | 自研 I18n Context | 支持 `en` / `zh`，基于 `messages.ts` 与 `{{var}}` 插值 |
| Markdown 渲染 | `marked` | `^18.0.5` |
| 编辑器 | `@monaco-editor/react` + `monaco-editor` | 代码编辑 |
| 终端 | `@xterm/xterm` + `@xterm/addon-fit` | WebSocket 终端 |
| 流程图 | `@xyflow/react` (React Flow) | 项目任务节点与依赖边可视化 |
| 图布局 | `@dagrejs/dagre` | 项目画布自动布局 |
| 拖拽 | `@dnd-kit/core` / `sortable` | 卡片拖拽排序 |
| Lint | ESLint 9 flat config | `@eslint/js` + `typescript-eslint` + `react-hooks` + `react-refresh` |
| 单元测试 | Vitest + jsdom + `@testing-library/react` | `__tests__/**/*.test.{ts,tsx}` 等 |
| E2E 测试 | Playwright | `__tests__/e2e/` |
| 性能分析 | `rollup-plugin-visualizer` | 可选开启 `VITE_BUNDLE_ANALYZE=true` |

**关键约束（来自 `.rules/frontend-and-testing.md`）：**
- Tailwind v4 JIT 下**动态类名不可靠**（如 `space-y-${gap}`），必须使用静态映射表。
- 不要嵌套 `@dnd-kit` 的 draggable wrapper；`CardGrid` 已内置 draggable，render 内容不能再包一层。

---

## 2. UI/UX 设计体系

### 2.1 设计基调
- **风格**：类 Apple / 现代简约风，圆角大（`--radius: 0.75rem`）、柔和阴影、背景浅色 `#f7f7f8`。
- **字体**：Inter 为主，通过 CSS 变量 `--font-text` / `--font-display` 控制；支持 `sans-serif` / `serif` 切换（Settings 中）。
- **主题**：浅色/深色双主题，基于 `prefers-color-scheme: dark` 自动切换，全部通过 CSS 变量驱动。
- **强调色**：蓝色系（`--accent: #2563eb` / 深色 `#60a5fa`），语义色包含 success / warning / danger / info。

### 2.2 CSS 变量体系（`src/index.css`）
核心变量覆盖背景、前景、卡片、边框、输入框、焦点环、阴影、侧边栏、代码块、消息角色色等。例如：
- `--background`, `--foreground`, `--card`, `--border`, `--ring`
- `--shadow-pane`, `--shadow-card`, `--shadow-toolbar`
- `--color-msg-user`, `--color-msg-assistant`, `--color-msg-thinking`, `--color-msg-tool-call` 等（消息气泡角色色）

### 2.3 无障碍与交互细节
- 焦点可见样式统一：`*:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }`
- `Modal` 组件自带 focus trap（`useFocusTrap`）、ESC 关闭、backdrop 点击关闭、ARIA role/label。
- `SplitPane` 支持鼠标拖拽、键盘方向键调节宽度，并带有 `role="separator"` 与 ARIA value。
- 页面标题随路由切换自动更新。

### 2.4 消息 / 终端 UX
- 消息组件区分 `user / assistant / thinking / tool_call / tool_result / system_event` 六种类型，各自有不同颜色与展示形式。
- 终端统一封装在 `TerminalSessionConsole`，使用 xterm.js，样式覆盖 `.xterm-viewport` 背景为 `#0b1020`。

---

## 3. UI 组件体系

组件按职责分组，目录结构清晰：

```
src/components/
├── common/          # 应用级公共组件
│   ├── Layout.tsx           # 侧边栏 + Header + 主内容区
│   ├── ErrorBoundary.tsx    # 全局错误边界
│   ├── LoadingSpinner.tsx
│   ├── LocaleSwitcher.tsx
│   ├── Toast.tsx            # Toast 通知
│   └── LoadMoreSentinel.tsx
├── ui/              # 基础原子组件
│   ├── Button.tsx           # primary/secondary/danger/ghost，sm/md
│   ├── Input.tsx
│   ├── Textarea.tsx
│   ├── Select.tsx
│   ├── Modal.tsx
│   ├── Badge.tsx
│   ├── Alert.tsx
│   ├── StatusDot.tsx
│   ├── FormField.tsx
│   ├── PageHeader.tsx
│   ├── SectionCard.tsx
│   ├── SectionHeader.tsx
│   ├── EmptyState.tsx
│   ├── SkillToggleGroup.tsx
│   └── theme.ts             # 语义色静态类名映射
├── layout/          # 布局原子
│   ├── PageShell.tsx        # 圆角卡片外壳
│   ├── SplitPane.tsx        # 可拖拽左右分栏
│   ├── SectionStack.tsx     # 垂直分段间距
│   └── CardGrid.tsx         # 可拖拽卡片网格
├── messages/        # 聊天/任务消息相关
│   ├── MessageBubble.tsx
│   ├── MessageList.tsx
│   ├── AssistantBubble.tsx
│   ├── UserBubble.tsx
│   ├── ThinkingBlock.tsx
│   ├── ToolCallBlock.tsx
│   ├── ToolResultBlock.tsx
│   ├── SystemEventBlock.tsx
│   ├── TaskHeaderBar.tsx
│   ├── TaskMetadataDrawer.tsx
│   └── SafeMarkdown.tsx
├── project/         # 项目画布
│   ├── ProjectCanvas.tsx    # React Flow 画布
│   ├── ProjectSidebar.tsx
│   ├── ProjectDropZone.tsx
│   ├── TaskNode.tsx
│   └── layoutDagre.ts
├── terminal/        # 终端相关
│   ├── TerminalSessionConsole.tsx
│   ├── TerminalBenchCard.tsx
│   ├── TerminalBenchCardView.tsx
│   ├── useTerminalBenchSession.ts
│   └── useTerminalFitScheduling.ts
├── resources/       # 资源监控卡片
│   ├── SystemResourceCard.tsx
│   ├── TaskUsageCard.tsx
│   ├── CpuRing.tsx
│   ├── GpuBar.tsx
│   ├── MemoryBar.tsx
│   └── DraggableResourceCard.tsx
├── environment/     # Environment 选择器
├── file-browser/    # 文件树与文件查看器
├── literature/      # 文献订阅/论文卡片
├── settings/        # 设置子组件
├── dashboard/       # 仪表盘状态条
└── shared/          # 共享小件（Drawer、Pill）
```

### 3.1 原子组件设计特点
- **纯展示 + 受控**：Button、Input、Select 等均受控， props 明确。
- **静态类名映射**：如 `Button` 的 `variantClasses`、`SectionStack` 的 `GAP_CLASSES`，避免 Tailwind JIT 失效。
- **语义色调统一**：`theme.ts` 中的 `semanticToneClasses` 与 `semanticDotClasses` 在 Badge、Alert、StatusDot、会话状态徽章中复用。

### 3.2 复合组件设计
- `Layout`：提供全局侧边栏导航、Header、任务状态摘要、用户登出；侧边栏可折叠（`w-[56px]` / `w-[248px]`）。
- `SplitPane`：被 `TasksPage`、`ProjectsPage`、`SessionsPage` 等大量使用，支持左右双栏与折叠状态。
- `PageShell`：页面外层圆角卡片 + 阴影，统一内边距。

---

## 4. 状态管理

### 4.1 服务端状态：React Query
- 全局 `QueryClient` 由 `createAppQueryClient()` 创建，默认配置：
  - `staleTime: 5000`
  - `gcTime: 5000`
  - `refetchOnWindowFocus: false`
  - `refetchOnReconnect: false`
- 多处使用 `refetchInterval: 5000` 实现任务/会话/资源等实时轮询。
- 乐观更新/本地缓存更新：如 `TasksPage` 创建任务后 `setQueryData` 立即刷新列表；删除任务时同步过滤列表缓存。

### 4.2 本地应用状态：React Context
1. **`AuthContext`**（`src/contexts/AuthContext.tsx`）
   - 维护 `user`、`loading`、登录/注册/登出。
   - 启动时读取 `localStorage` 中 refresh token，调用 `/auth/refresh` 自动续期。
   - access token 仅存内存，refresh token 明确注释存在 XSS 风险（开发阶段）。

2. **`SettingsContext`**（`src/settings/context.tsx`）
   - 维护 WebUI 设置：默认路由、终端/编辑器字体、外观字体、任务配置、研究 Agent Profile、LLM Provider、每个 project/environment 的默认值。
   - 设置持久化到 `localStorage`（通过 `src/settings/storage.ts`）。
   - 自动从后端 `/settings/codex-defaults` 拉取 Codex 默认配置并合并到 profile。

3. **`I18nContext`**（`src/i18n/index.tsx`）
   - 维护 `locale`、`setLocale`、`toggleLocale`、`t` 翻译函数。
   - 自动检测浏览器语言，持久化到 `localStorage`。

4. **`ToastProvider`**（`src/components/common/Toast.tsx`）
   - 全局轻通知，提供 `useToast` hook。

### 4.3 局部状态
- 页面级状态基本使用 `useState` + `useCallback`，如 `TasksPage` 的选择任务、侧边栏宽度、创建弹窗等。
- 复杂表单如 `TaskCreateForm` 使用多个 `useState` 组合管理。
- `ProjectCanvas` 使用 `localStorage` 持久化节点布局（`ainrf:project-layout:${projectId}`）。

### 4.4 状态管理未使用 Redux / Zustand
当前完全采用 **React Context + React Query + useState**，没有引入 Redux、Zustand、Jotai 等第三方全局状态库。这种选择在当前规模（约 22k 行前端代码）下是合理的，但需关注 `SettingsContext` 与 `AuthContext` 的 re-render 范围。

---

## 5. 数据流

### 5.1 数据层结构
```
src/api/
├── client.ts      # fetch 封装、access token、401 自动刷新、ApiError
├── endpoints.ts   # 所有 REST API 调用函数（约 700 行）
├── mock.ts        # VITE_USE_MOCK=true 时的 mock 数据
└── index.ts       # 导出
```

### 5.2 API Client 设计（`client.ts`）
- 基于原生 `fetch` 封装。
- 统一注入 `Authorization: Bearer <access_token>`。
- 自动处理 401：共享单一 refresh promise 防止并发刷新请求重复。
- 解析后端错误时优先取 `detail / message / error / title / reason`。
- 记录 `X-Request-ID` 用于与后端日志关联。
- 注意：`api_key` 通过 URL query 注入 EventSource 流（原生 EventSource 不能自定义 header）。

### 5.3 请求路由与代理
- 开发/预览服务器通过 `vite.proxy.ts` 代理：
  - `/api/*` → 后端（默认 `http://127.0.0.1:8000`），并 strip `/api` 前缀
  - `/code/*` → 后端
  - `/terminal/*` → 后端 WebSocket
- 代理自动注入 `X-API-Key` 头（来自 `AINRF_WEBUI_API_KEY`）。
- 前端不直接持有服务端 API key，仅通过同源代理访问。

### 5.4 Mock 机制
- `endpoints.ts` 中每个函数都检查 `import.meta.env.VITE_USE_MOCK === 'true'`。
- `mock.ts` 提供完整 mock 数据，便于离线开发或 Storybook 式测试。

### 5.5 流式数据
- 任务输出使用 SSE（Server-Sent Events）：`useTaskStream` hook 通过 `EventSource` 连接 `/api/tasks/:id/stream`。
- 终端使用 WebSocket（`terminal_ws_url`），在 `useTerminalBenchSession` 中管理连接。

### 5.6 数据流总结
```
用户交互 → 页面/组件 useState
        → React Query mutation / query
        → endpoints.ts → api.client.ts → fetch → Vite proxy → 后端
        → 响应更新 Query Cache / 本地状态 → UI 重新渲染
```

---

## 6. 布局设计

### 6.1 全局布局（`Layout.tsx`）
- **左侧固定侧边栏**：宽 56px（折叠）/ 248px（展开），包含 Logo、导航项、用户区、登出。
- **顶部 Header**：吸顶，左侧显示当前页面标题，右侧显示任务状态摘要与语言切换。
- **主内容区**：`flex-1`，内部页面使用 `PageShell` 或自定义布局。
- 整体 `h-screen overflow-hidden`，页面内部各自滚动。

### 6.2 页面内布局模式
- **三栏/双栏分栏**：`TasksPage` 为“左任务列表 - 中详情 - 右元数据”三栏；`ProjectsPage` 为“左项目列表 - 右画布”双栏；`SessionsPage` 为双栏。
- **拖拽分栏**：`SplitPane` 实现，最小 260px、最大 520px，支持键盘与鼠标。
- **卡片网格**：`ResourcesPage` / `DashboardPage` 使用 `CardGrid` / `SectionCard` 组织。
- **模态弹窗**：任务创建、任务详情、项目创建、设置中的 LLM Provider 编辑等均使用 `Modal`。

### 6.3 响应式
- 当前主要以桌面端为主；代码中可见少量 `sm:block` 类隐藏元素，移动端适配不是重点。
- 侧边栏折叠、任务侧边栏折叠提供空间效率。

### 6.4 布局组件复用
- `PageShell`：统一圆角白卡片外壳。
- `SectionStack`：统一段落间距（gap 静态映射）。
- `SplitPane`：所有需要分栏的页面复用同一组件。

---

## 7. 页面划分

`src/pages/` 共 15+ 个页面，路由定义在 `App.tsx`：

| 路由 | 页面组件 | 功能描述 | 权限 |
|------|----------|----------|------|
| `/` | `RootRedirect` | 按用户设置跳转到默认页 | 已登录 |
| `/projects` | `ProjectsPage` | 项目列表 + React Flow 任务画布 + 任务详情弹窗 | 已登录 |
| `/terminal` | `TerminalPage` | 个人终端 / managed task 终端 | 已登录 |
| `/tasks` | `TasksPage` | 任务列表、任务详情、任务元数据、创建任务 | 已登录 |
| `/workspaces` | `WorkspacesPage` | Workspace 管理 | 已登录 |
| `/workspace-browser` | `FileBrowserPage` | 文件浏览器 / code-server 入口 | 已登录 |
| `/environments` | `EnvironmentsPage` | Environment 管理与检测 | 已登录 |
| `/resources` | `ResourcesPage` | 系统资源监控面板 | 已登录 |
| `/sessions` | `SessionsPage` | 会话管理（admin） | admin |
| `/timeline` | `TimelinePage` | Gantt 时间线（admin） | admin |
| `/literature` | `LiteraturePage` | 文献订阅与论文列表 | 已登录 |
| `/settings` | `SettingsPage` | 系统设置、LLM Provider、用户、权限 | 已登录 |
| `/login` | `LoginPage` | 登录 | 未登录 |
| `/register` | `RegisterPage` | 注册 | 未登录 |
| `*` (must_change_password) | `ChangePasswordPage` | 强制改密 | 已登录但需改密 |

### 7.1 页面结构细分
- **任务相关页面**：
  - `TasksPage` 为主入口；
  - `TaskCreateForm`、`TaskDetailPage`、`TaskList`、`TaskInputBar`、`TaskSkillPicker`、`taskPresets.ts` 等放在 `pages/tasks/`；
  - `useTaskStream.ts`、`useTaskHistory.ts`、`useTaskMessages.ts`、`useTaskActions.ts` 为任务相关自定义 hooks。

- **会话相关页面**：
  - `SessionsPage` + `pages/sessions/SessionList.tsx` + `SessionDetail.tsx` + `AttemptChain.tsx`。

- **设置页面**：
  - `SettingsPage` 约 1830 行，集成多个 Tab：
    - `CollaboratorsTab`
    - `EnvAccessTab`
    - `LlmProvidersTab`
    - `MonitoringTab`
    - `UsersTab`
    - `LlmProviderEditDialog`

- **文献页面**：
  - `LiteraturePage` + `components/literature/`（PaperCard、PaperFeed、SubscriptionSidebar、ConvertToTaskDialog）。

- **Dashboard**：
  - `DashboardPage` 目前偏“调试/入口”性质，展示 health、environment selector、terminal bench。

### 7.2 懒加载
- `App.tsx` 中所有页面均使用 `React.lazy()` 按需加载，配合 `Suspense` fallback。

---

## 8. 实现状况与工程质量

### 8.1 代码规模
- 前端 `src/` 下约 **153 个 TS/TSX/CSS 文件**，总代码量约 **22,044 行**。
- 最长的文件：`src/i18n/messages.ts`（2133 行，中英双语文案）、`src/pages/SettingsPage.tsx`（1830 行）、`src/api/mock.ts`（1272 行）、`src/types/index.ts`（907 行）。

### 8.2 类型体系
- 后端 DTO 与前端类型集中定义在 `src/types/index.ts`。
- TypeScript 严格度适中：启用 `noUnusedLocals`、`noUnusedParameters`、`noFallthroughCasesInSwitch`、`verbatimModuleSyntax`。
- 未开启 `strict: true`（配置中未显式设置），但基本类型覆盖较好。

### 8.3 测试覆盖
- **单元测试**：Vitest + jsdom + Testing Library，测试文件 39 个，覆盖主要页面（Login、Register、Projects、Tasks、Sessions、Workspaces、Settings、Terminal、FileBrowser、Resources、Timeline、ChangePassword）。
- **E2E 测试**：Playwright，位于 `__tests__/e2e/`，包含 agentic-researcher、auth、projects、task-retry 场景。
- **性能测试**：`__tests__/perf/` 包含 streaming 渲染基准。
- 注意：大量组件尚未被单元测试直接覆盖（如 `MessageBubble`、`ProjectCanvas` 等），测试更多集中在页面级集成。

### 8.4 构建与部署
- 已配置完整构建流程：`npm run build` 会先写 `build-info.json`，再执行 `tsc -b` 与 `vite build`。
- `dist/` 目录存在最近一次构建产物，包含代码分割后的 chunk（`terminal-vendor`、`app-vendor`、`vendor` 等）。
- 构建时代理配置与生产 nginx 配置需要保持一致；README 强调通过 `scripts/webui.sh` 一键启动前后端。

### 8.5 已发现的工程风险与改进点
1. **SettingsPage 过大**：1830 行，包含多个 Tab 与 Dialog 实现，建议拆分为独立子组件文件。
2. **i18n 文案集中**：`messages.ts` 2133 行，中英双语混合，随着功能增长会越来越庞大，可按页面/模块拆分。
3. **严格模式未开启**：虽然代码质量较好，但开启 `strict: true` 可进一步降低运行时类型风险。
4. **Canvas 布局持久化依赖 localStorage**：跨设备/浏览器不共享，且大项目节点多时 JSON 可能较大。
5. **测试覆盖偏向页面级**：复杂交互组件（React Flow 画布、终端、拖拽卡片）缺少直接单元测试，更多依赖 E2E。
6. **无视觉回归测试**：未引入 Chromatic / Loki 等视觉回归工具。

---

## 9. 总结

AINRF 前端是一个以 **React 19 + Vite + Tailwind CSS v4 + React Query + React Router v7** 为核心的现代化单页应用。整体架构清晰：

- **UI/UX** 采用统一的 CSS 变量主题、语义色体系、圆角卡片式布局，偏向桌面端生产力工具风格。
- **组件体系** 分层明确：原子组件 `ui/`、布局组件 `layout/`、业务组件按领域分组（messages、project、terminal、resources 等）。
- **状态管理** 采用轻量方案：React Query 负责服务端状态，Context 负责认证/设置/国际化，useState 管理局部 UI 状态。
- **数据流** 统一通过 `api/endpoints.ts` → `api/client.ts` → Vite proxy → 后端，支持 REST、SSE 流、WebSocket 终端。
- **布局** 以全局侧边栏 + 页面内 `SplitPane` 分栏为主，适合多面板信息密度高的场景。
- **页面** 覆盖项目、任务、终端、环境、workspace、文件、资源、会话、时间线、文献、设置等完整 AINRF 功能域。

当前实现已经具备生产级雏形，代码量与组件分层都达到一定规模，后续可在组件拆分、严格类型、复杂组件单测、视觉回归方面继续补强。

---

*报告生成时间：2026/06/14*
