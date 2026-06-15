# AINRF 前端重构与重设计方案

> 目标：在保持现有 React + Vite + Tailwind 技术栈的前提下，提升可扩展性、维护性，并打造更贴近 Apple Style 的简洁、精致 UI。
> 设计理念代号：**Prism Console** —— 以 Apple 的克制、透明与层级为基础，注入温暖的石质中性色、深靛蓝主色与琥珀信号色，形成既有辨识度又不失专业感的科研控制台美学。

---

## 1. 当前问题诊断（基于调研）

| 问题域 | 现状 | 影响 |
|--------|------|------|
| 巨型组件 | `SettingsPage.tsx` 1830 行，`messages.ts` 2133 行 | 可读性差、测试困难、协作冲突 |
| Context 过大 | `SettingsContext` 承载所有设置 + LLM Provider + Project 默认值 | 任何设置改动触发大面积重渲染 |
| 目录按类型组织 | `components/ui/`, `components/common/` 等 | 新功能跨目录 scattered，难以定位 |
| 测试策略 | 偏页面级集成，复杂组件单测少 | 画布、终端、消息气泡回归依赖 E2E，成本高 |
| 类型严格度 | 未开启 `strict: true` | 边缘类型风险 |
| 动态主题 | 仅支持 light/dark 系统偏好 | 无法细粒度控制，缺少品牌辨识度 |

---

## 2. 设计方向：Prism Console

### 2.1 设计关键词
- **透明层级**（Translucency）：用背景模糊、细边框、阴影建立空间层次，类似 Apple 的 HUD 面板。
- **温暖中性**（Warm Neutrals）：避免冷灰，使用石色（stone）与暖板岩色（warm slate）。
- **信号色彩**（Signal Colors）：深靛蓝（primary）、琥珀（running/warning）、翡翠绿（success）、珊瑚红（danger）。
- **字体编辑感**（Editorial Typography）：标题使用几何感字体，正文保持高可读性，数据等宽。
- **有目的的动效**（Purposeful Motion）：页面进入有节奏，交互有反馈，但绝不喧宾夺主。

### 2.2 设计 tokens（示例）

```css
/* design-tokens.css */
:root {
  /* Backgrounds */
  --prism-bg: #fafaf9;           /* stone-50 */
  --prism-bg-elevated: #ffffff;
  --prism-bg-secondary: #f5f5f4; /* stone-100 */
  --prism-bg-tertiary: #e7e5e4;  /* stone-200 */

  /* Text */
  --prism-text: #1c1917;         /* stone-900 */
  --prism-text-secondary: #57534e; /* stone-600 */
  --prism-text-tertiary: #a8a29e;  /* stone-400 */

  /* Accents */
  --prism-primary: #4f46e5;      /* indigo-600 */
  --prism-primary-hover: #4338ca;
  --prism-primary-soft: rgba(79, 70, 229, 0.08);
  --prism-primary-border: rgba(79, 70, 229, 0.22);

  --prism-amber: #f59e0b;
  --prism-emerald: #10b981;
  --prism-coral: #ef4444;

  /* Surfaces */
  --prism-surface: #ffffff;
  --prism-surface-hover: #fafaf9;
  --prism-border: rgba(28, 25, 23, 0.08);
  --prism-border-strong: rgba(28, 25, 23, 0.14);

  /* Effects */
  --prism-radius: 0.875rem;
  --prism-radius-sm: 0.625rem;
  --prism-shadow-sm: 0 1px 2px rgba(28, 25, 23, 0.04);
  --prism-shadow-md: 0 4px 12px rgba(28, 25, 23, 0.06), 0 1px 3px rgba(28, 25, 23, 0.04);
  --prism-shadow-lg: 0 12px 32px rgba(28, 25, 23, 0.08), 0 4px 8px rgba(28, 25, 23, 0.04);
  --prism-glass: rgba(255, 255, 255, 0.72);

  /* Typography */
  --font-display: 'Outfit', 'SF Pro Display', system-ui, sans-serif;
  --font-body: 'DM Sans', 'SF Pro Text', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
}

@media (prefers-color-scheme: dark) {
  :root {
    --prism-bg: #0c0a09;
    --prism-bg-elevated: #171412;
    --prism-bg-secondary: #1c1917;
    --prism-bg-tertiary: #292524;

    --prism-text: #fafaf9;
    --prism-text-secondary: #a8a29e;
    --prism-text-tertiary: #78716c;

    --prism-primary: #818cf8;
    --prism-primary-hover: #a5b4fc;
    --prism-primary-soft: rgba(129, 140, 248, 0.12);
    --prism-primary-border: rgba(129, 140, 248, 0.28);

    --prism-surface: #171412;
    --prism-surface-hover: #1c1917;
    --prism-border: rgba(255, 255, 255, 0.08);
    --prism-border-strong: rgba(255, 255, 255, 0.14);
    --prism-glass: rgba(23, 20, 18, 0.72);
  }
}
```

### 2.3 字体策略
- **Display**: `Outfit`（Google Fonts）— 几何感、现代、比 Inter 更有辨识度。
- **Body**: `DM Sans` — 高可读性、温暖。
- **Mono**: `JetBrains Mono` — 科研/代码气质。

加载方式：
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&family=Outfit:wght@500;600;700&display=swap" rel="stylesheet">
```

---

## 3. 组件架构重构

### 3.1 目录结构：从“按类型”到“按功能域”

```
src/
├── app/                    # 应用启动、全局 providers、路由
│   ├── App.tsx
│   ├── routes.tsx
│   ├── providers/
│   └── index.css
├── features/               # 按业务域组织
│   ├── auth/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── api.ts
│   │   └── types.ts
│   ├── tasks/
│   │   ├── components/
│   │   │   ├── TaskCreateForm/
│   │   │   ├── TaskDetail/
│   │   │   ├── TaskList/
│   │   │   └── TaskStream/
│   │   ├── hooks/
│   │   ├── api.ts
│   │   ├── mutations.ts
│   │   ├── queries.ts
│   │   └── types.ts
│   ├── projects/
│   ├── terminal/
│   ├── workspaces/
│   ├── environments/
│   ├── sessions/
│   ├── literature/
│   ├── settings/
│   └── dashboard/
├── design-system/          # 共享设计系统
│   ├── tokens/
│   ├── primitives/         # Button, Input, Modal 等无业务依赖
│   ├── patterns/           # SplitPane, PageShell, SectionStack
│   └── hooks/
├── shared/                 # 纯工具
│   ├── i18n/
│   ├── utils/
│   └── types/
└── tests/
```

**收益**：
- 新增功能只需在一个 `features/xxx/` 目录内开发，不污染全局。
- 设计系统与业务解耦，便于 Storybook/文档化。
- 删除功能时直接删除一个目录。

### 3.2 设计系统组件：Headless + Styled 分层

当前 `components/ui/Button.tsx` 直接把样式与逻辑写死。建议拆分为：

```tsx
// design-system/primitives/Button/Button.tsx
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ variant = 'primary', size = 'md', isLoading, children, className, disabled, ...rest }, ref) {
    return (
      <button
        ref={ref}
        className={buttonStyles({ variant, size, isLoading, className })}
        disabled={disabled || isLoading}
        {...rest}
      >
        {isLoading ? <Spinner size="sm" /> : children}
      </button>
    );
  }
);
```

```tsx
// design-system/primitives/Button/styles.ts
import { cva } from 'class-variance-authority'; // 或手写静态映射

export const buttonStyles = cva(
  'inline-flex items-center justify-center rounded-[var(--prism-radius-sm)] font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--prism-primary)] focus-visible:ring-offset-2',
  {
    variants: {
      variant: {
        primary: 'bg-[var(--prism-primary)] text-white hover:bg-[var(--prism-primary-hover)] shadow-[var(--prism-shadow-sm)] active:scale-[0.98]',
        secondary: 'bg-[var(--prism-surface)] text-[var(--prism-text)] border border-[var(--prism-border)] hover:bg-[var(--prism-surface-hover)] hover:border-[var(--prism-border-strong)] active:scale-[0.98]',
        ghost: 'text-[var(--prism-text-secondary)] hover:bg-[var(--prism-bg-secondary)] hover:text-[var(--prism-text)]',
        danger: 'bg-[var(--prism-coral)]/10 text-[var(--prism-coral)] border border-[var(--prism-coral)]/20 hover:bg-[var(--prism-coral)]/15 active:scale-[0.98]',
      },
      size: {
        sm: 'h-8 px-3 text-xs gap-1.5',
        md: 'h-10 px-4 text-sm gap-2',
        lg: 'h-11 px-5 text-sm gap-2',
      },
    },
  }
);
```

**推荐引入 `class-variance-authority`（CVA）**：在保持 Tailwind 静态类名的同时，获得清晰的 variant API。

### 3.3 复合组件模式示例：Card

```tsx
// design-system/primitives/Card/Card.tsx
import { createContext, useContext, type ReactNode } from 'react';

const CardContext = createContext(false);

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <CardContext.Provider value={true}>
      <div className={`rounded-[var(--prism-radius)] border border-[var(--prism-border)] bg-[var(--prism-surface)] shadow-[var(--prism-shadow-sm)] ${className}`}>
        {children}
      </div>
    </CardContext.Provider>
  );
}

export function CardHeader({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`flex items-center justify-between border-b border-[var(--prism-border)] px-5 py-4 ${className}`}>{children}</div>;
}

export function CardBody({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`p-5 ${className}`}>{children}</div>;
}
```

---

## 4. 状态管理重构

### 4.1 拆分 `SettingsContext`

当前 `SettingsContext` 包含 20+ 个方法。建议拆分为：

```
src/features/settings/
├── contexts/
│   ├── SettingsProvider.tsx       # 仅负责持久化与聚合
│   ├── GeneralSettingsContext.tsx # 路由、字体、外观
│   ├── TaskDefaultsContext.tsx    # 项目/环境默认配置
│   └── LlmProvidersContext.tsx    # LLM Provider CRUD
├── hooks/
│   ├── useGeneralSettings.ts
│   ├── useTaskDefaults.ts
│   └── useLlmProviders.ts
├── storage.ts
└── types.ts
```

每个 Context 只暴露自己领域的状态，组件按需订阅，减少重渲染。

### 4.2 React Query 规范化

建议每个 feature 拥有自己的 `queries.ts` / `mutations.ts`：

```tsx
// features/tasks/queries.ts
import { useQuery } from '@tanstack/react-query';
import { getTasks } from './api';

export const taskKeys = {
  all: ['tasks'] as const,
  list: (params: { archived: boolean; sort: string }) => [...taskKeys.all, 'list', params] as const,
  detail: (id: string) => [...taskKeys.all, 'detail', id] as const,
};

export function useTasks(params: { archived: boolean; sort: string }) {
  return useQuery({
    queryKey: taskKeys.list(params),
    queryFn: () => getTasks(params),
    refetchInterval: 5000,
  });
}
```

```tsx
// features/tasks/mutations.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createTask } from './api';
import { taskKeys } from './queries';

export function useCreateTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createTask,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
}
```

**收益**：
- Query key 集中管理，避免拼写错误。
- 缓存失效逻辑统一。
- 新开发者无需记忆全局 query key 约定。

---

## 5. 页面重设计示例：TasksPage 信息架构

### 5.1 当前问题
- 三栏布局信息密度高，但缺少视觉层次。
- 任务列表与元数据抽屉同时存在，新手可能困惑。

### 5.2 重构后架构

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Tasks              [Search] [Filter] [+ New Task]   │
├──────────┬──────────────────────────────────────────────────┤
│ Task     │  Task Detail                                    │
│ Sidebar  │  ┌────────────────────────────────────────────┐ │
│ (collaps)│  │ Header: Title + Status + Actions             │ │
│          │  ├────────────────────────────────────────────┤ │
│          │  │ Message Stream                               │ │
│          │  │                                              │ │
│          │  │                                              │ │
│          │  ├────────────────────────────────────────────┤ │
│          │  │ Input Bar                                    │ │
│          │  └────────────────────────────────────────────┘ │
│          │  [Metadata toggle → Drawer from right]          │
└──────────┴──────────────────────────────────────────────────┘
```

- 默认只展示两栏，元数据通过右侧抽屉（`Drawer`）展开，降低视觉噪音。
- 任务列表使用 `StatusDot` + 标题 + 引擎标签，状态色彩更克制。
- 消息区域使用更清晰的卡片式气泡，thinking/tool 折叠更自然。

---

## 6. 动效与交互规范

### 6.1 原则
- 所有动画使用 CSS transition/keyframes，避免引入大型动画库。
- 尊重 `prefers-reduced-motion`。
- 动效服务于“空间定位”与“状态反馈”，而非装饰。

### 6.2 常用模式

```css
/* 页面进入 */
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-enter {
  animation: fade-in-up 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* 列表 stagger */
.stagger-children > * {
  animation: fade-in-up 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.stagger-children > *:nth-child(1) { animation-delay: 0ms; }
.stagger-children > *:nth-child(2) { animation-delay: 40ms; }
.stagger-children > *:nth-child(3) { animation-delay: 80ms; }

/* 按钮反馈 */
.btn-press:active { transform: scale(0.97); }

/* Modal 进入 */
.modal-backdrop { transition: opacity 0.2s ease; }
.modal-panel { transition: opacity 0.2s ease, transform 0.25s cubic-bezier(0.16, 1, 0.3, 1); }
```

---

## 7. 实施路线

### Phase 1：设计系统地基（1-2 周）
- [ ] 建立 `design-system/` 目录与 `design-tokens.css`
- [ ] 重构 Button、Input、Modal、Badge、Card 等原子组件为 CVA + 复合组件
- [ ] 引入 Outfit / DM Sans / JetBrains Mono 字体
- [ ] 建立 Storybook 或简单文档页

### Phase 2：目录与状态重构（2-3 周）
- [ ] 迁移到 `features/` 目录结构
- [ ] 拆分 `SettingsContext` 为多个领域 Context
- [ ] 规范化 React Query keys（`queries.ts` / `mutations.ts`）
- [ ] 开启 TypeScript `strict: true` 并修复类型问题

### Phase 3：页面级重设计（3-4 周）
- [ ] 重构 `Layout`：更精致的侧边栏、玻璃态 Header
- [ ] 重构 `TasksPage`：两栏 + 元数据抽屉
- [ ] 重构 `ProjectsPage`：React Flow 主题适配新 tokens
- [ ] 重构 `SettingsPage`：拆分为多个 Tab 子页面/组件
- [ ] 统一 `messages.ts` 文案，按 feature 拆分

### Phase 4：质量加固（持续）
- [ ] 为 `ProjectCanvas`、`MessageBubble`、`TerminalSessionConsole` 增加单元测试
- [ ] 引入视觉回归测试（如 Chromatic）
- [ ] 性能审计：bundle 体积、React Query 缓存策略

---

## 8. 立即可以落地的最小改动

如果希望先验证方向，建议先做以下 3 件事：

1. **替换设计 tokens 文件**：新建 `src/design-system/tokens/design-tokens.css`，逐步替换 `index.css` 中的变量。
2. **重构 `Button` 组件**：使用 CVA，统一四种 variant，加入按压动效。
3. **拆分 `SettingsPage`**：将 5 个 Tab 拆成独立文件，Settings 入口仅做路由/Tab 切换。

---

## 9. 风险与注意事项

- **Tailwind v4 动态类名约束不变**：重构后仍需使用静态类名或 CVA。
- **不要一次性重写所有页面**：渐进迁移，优先高频率页面（Tasks、Projects、Settings）。
- **保持 API 层稳定**：`api/endpoints.ts` 可在迁移初期保留，后续再按 feature 拆分。
- **i18n 拆分需同步**：避免文案散落在各 feature 后难以统一管理。

---

*提案生成时间：2026/06/14*
