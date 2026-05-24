# LiteraturePage 视觉对齐设计

## 背景

文献追踪页面（LiteraturePage）当前使用 `PageShell` 包裹 `SplitPane` 实现两栏布局，但在 `PageShell` 和 `SplitPane` 之间插入了一个带 padding 的 wrapper div（`<div class="space-y-6 p-4">`），导致两栏无法占满 `PageShell` 内部的高和宽。同时，`SubscriptionSidebar`、`PaperFeed` 和 `PaperCard` 中使用了原生 HTML 控件和自定义样式，与项目中其他页面使用的统一组件库风格不一致。

## 目标

1. 两栏布局占满 `PageShell` 内部的高和宽
2. 文献追踪页面在视觉上与 TasksPage、ProjectsPage 等其他使用 `SplitPane` 的页面保持一致
3. 统一使用项目现有的 `components/ui` 组件，消除原生 HTML 控件的视觉差异

## 方案

采用方案 B（完全对齐）：移除 wrapper div + 样式统一。

## 详细设计

### 1. LiteraturePage.tsx — 结构层

移除 `PageShell` 和 `SplitPane` 之间的 `<div class="space-y-6 p-4">` wrapper，`SplitPane` 直接作为 `PageShell` 的唯一子元素。保留所有 state、data fetching 和 mutation 逻辑不变。

```tsx
<PageShell>
  <SplitPane
    sidebar={<SubscriptionSidebar subscriptions={subscriptions} />}
    sidebarWidth={sidebarWidth}
    onSidebarWidthChange={setSidebarWidth}
    sidebarMinWidth={220}
    sidebarMaxWidth={400}
  >
    <PaperFeed
      subscriptions={subscriptions}
      onConvertToTask={handleConvertToTask}
    />
  </SplitPane>
</PageShell>
```

### 2. SubscriptionSidebar — 样式对齐

`SplitPane` 的 `aside` 已经提供 `bg-[var(--sidebar)] p-3 overflow-y-auto`，因此 `SubscriptionSidebar` 不再需要外层 `flex h-full flex-col` 容器。

| 元素 | 当前 | 改为 |
|------|------|------|
| 标题文字 | 默认黑色 | `text-[var(--sidebar-foreground)]` |
| "新建订阅"按钮 | 自定义蓝色 `<button>` | `Button` 组件 |
| 表单输入框 | 原生 `<input>` | `Input` 组件 |
| 表单下拉框 | 原生 `<select>` | `Select` 组件 |
| 订阅列表项 | `bg-[var(--surface)]` 卡片 | 轻量列表项：底边框分隔 + hover `bg-[var(--sidebar-primary)]`，与 TaskList 风格一致 |
| 分类标签 | 圆角 badge 样式 | 保持圆角 badge，但颜色语义化 |

### 3. PaperFeed — 样式对齐

`SplitPane` 的 `main` 已经提供 `bg-[var(--bg)] p-4 overflow-y-auto`。

| 元素 | 当前 | 改为 |
|------|------|------|
| 订阅筛选下拉框 | 原生 `<select>` | `Select` 组件 |
| "未读 only"复选框 | 原生 `<input type="checkbox">` | 添加项目统一的 checkbox 样式类 |
| 刷新按钮 | 原生 `<button>` | `Button variant="secondary"`，带 `RefreshCw` 图标 |
| 列表容器 | `flex-1 space-y-3 overflow-y-auto` | 保持 `flex-1 overflow-y-auto`，去掉 `space-y-3`（由 PaperCard 的 margin 处理） |

### 4. PaperCard — 控件统一

| 元素 | 当前 | 改为 |
|------|------|------|
| 卡片背景 | `bg-[var(--surface)]` | 保持不变（在 `bg-[var(--bg)]` 上有良好对比度） |
| Mark Read 按钮 | 原生 `<button>` | `Button variant="secondary"` |
| View arXiv 链接 | `<a>` 标签 | `Button variant="secondary"`，`as="a"` |
| Convert to Task 按钮 | 原生 `<button>` | `Button variant="primary"` |

## 不变的部分

- `SplitPane` 组件本身：已与其他页面完全一致，无需修改
- `PaperCard` 的卡片结构、圆角、边框、hover shadow：与项目中其他卡片一致，保持不变
- AI Summary 折叠交互、AI Practice Note 展示逻辑：功能不变
- 数据获取和 mutation 逻辑：保持不变

## 依赖

- `components/ui` 中的 `Button`、`Input`、`Select` 组件
- `lucide-react` 中的 `RefreshCw` 图标
