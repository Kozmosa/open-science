# Frontend Testing Reorganization Design

## 目标

重构前端测试目录结构，补齐页面集成测试，引入 Playwright E2E 测试框架，形成三层测试金字塔。

## 目录结构

```
frontend/
├── __tests__/
│   ├── unit/                    # 纯函数/工具测试
│   │   ├── api/                 # client, endpoints, environments
│   │   ├── i18n/
│   │   ├── settings/
│   │   ├── hooks/
│   │   └── utils/
│   ├── components/              # 组件单元 + 交互测试
│   │   ├── ui/                  # Button, SkillToggleGroup, Modal
│   │   ├── project/             # ProjectCanvas, TaskNode
│   │   ├── terminal/
│   │   ├── token/
│   │   └── common/              # Layout, Toast
│   ├── pages/                   # 页面集成测试 (msw + testing-library)
│   │   ├── LoginPage.test.tsx
│   │   ├── ProjectsPage.test.tsx
│   │   ├── TasksPage.test.tsx
│   │   ├── SettingsPage.test.tsx
│   │   └── ...
│   └── e2e/                     # Playwright E2E 测试
│       ├── auth.spec.ts         # 登录/注册/修改密码
│       ├── projects.spec.ts     # Canvas 交互
│       ├── terminal.spec.ts
│       └── ...
├── playwright.config.ts
└── vitest.config.ts             # 更新路径
```

## 测试策略

### Layer 1: Unit Tests (vitest, 保持)

- 纯函数、工具函数、hooks、settings storage
- 已有：12 文件，保留后迁移到 `__tests__/unit/`
- 新增：无

### Layer 2: Component Tests (vitest + testing-library, 保持)

- 组件渲染、交互、props、事件
- 已有：13 文件，保留后迁移到 `__tests__/components/`
- 新增：Modal、Layout、TaskNode、FileTree 组件测试

### Layer 3: Page Integration Tests (vitest + testing-library + msw, 补齐)

- 完整页面渲染，mock API 响应，覆盖用户流程
- 已有：8 文件（Environments, Resources, Sessions, Settings, Tasks, Terminal, Timeline, Workspaces）
- 新增：
  - `LoginPage.test.tsx` — 登录成功/失败、重定向
  - `RegisterPage.test.tsx` — 注册提交、审批提示
  - `ChangePasswordPage.test.tsx` — 修改密码流程
  - `ProjectsPage.test.tsx` — Canvas 渲染、任务创建表单
  - `FileBrowserPage.test.tsx` — 文件列表、Monaco 懒加载

### Layer 4: E2E Tests (Playwright, 新增)

- 真实浏览器，真实后端（或 mock server）

| Suite | 用户故事 |
|-------|---------|
| auth | 登录 → 首页 → 登出 |
| projects | 打开项目 → 创建 task → Canvas 可见 → 自动连线 |
| terminal | 打开终端 → 输入命令 → 看到输出 |
| settings | 打开设置 → 切换 tab → 修改配置 |

## 新增依赖

```json
"msw": "^2.x",
"@playwright/test": "^1.x"
```

## 文件迁移映射

| 原路径 | 新路径 |
|--------|--------|
| `src/api/client.test.ts` | `__tests__/unit/api/client.test.ts` |
| `src/api/endpoints.test.ts` | `__tests__/unit/api/endpoints.test.ts` |
| `src/api/environments.test.ts` | `__tests__/unit/api/environments.test.ts` |
| `src/queryClient.test.ts` | `__tests__/unit/api/queryClient.test.ts` |
| `src/settings/storage.test.ts` | `__tests__/unit/settings/storage.test.ts` |
| `src/hooks/useCardLayout.test.ts` | `__tests__/unit/hooks/useCardLayout.test.ts` |
| `src/i18n/LocaleSwitcher.test.tsx` | `__tests__/unit/i18n/LocaleSwitcher.test.tsx` |
| `src/terminal-contract.test.ts` | `__tests__/unit/utils/terminal-contract.test.ts` |
| `src/vite-proxy.test.ts` | `__tests__/unit/utils/vite-proxy.test.ts` |
| `src/components/ui/Button.test.tsx` | `__tests__/components/ui/Button.test.tsx` |
| `src/components/ui/SkillToggleGroup.test.tsx` | `__tests__/components/ui/SkillToggleGroup.test.tsx` |
| `src/components/project/ProjectCanvas.test.tsx` | `__tests__/components/project/ProjectCanvas.test.tsx` |
| `src/components/terminal/TerminalBenchCard.test.tsx` | `__tests__/components/terminal/TerminalBenchCard.test.tsx` |
| `src/components/terminal/TerminalSessionConsole.test.tsx` | `__tests__/components/terminal/TerminalSessionConsole.test.tsx` |
| `src/components/token/TokenFlowBar.test.tsx` | `__tests__/components/token/TokenFlowBar.test.tsx` |
| `src/components/environment/EnvironmentSelectorPanel.test.tsx` | `__tests__/components/environment/EnvironmentSelectorPanel.test.tsx` |
| `src/App.test.tsx` | `__tests__/App.test.tsx` |
| `src/pages/*.test.tsx` (8 文件) | `__tests__/pages/*.test.tsx` |

## 验证

1. `npx vitest run` — 全部 119+ 测试通过
2. `npx playwright test` — E2E 套件通过
3. `cd frontend && node_modules/.bin/tsc -b` — 类型检查通过
4. 100% 原有测试迁移后无 broken reference
