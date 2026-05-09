# TaskDetail Interactions — Message Overflow, Resizable Split, Panel Toggle

## Goal

修复 TaskDetail 页面的三个交互问题：1) 长消息（尤其是 stderr JSON）导致消息流区域横向溢出；2) 对话流面板与详情面板之间的分割线无法拖动调整宽度；3) 详情面板右上角的展开/折叠按钮改为集成在分割线中央的悬浮按钮组。

## Architecture

- **消息层**：`MessageBlocks.tsx` 中 `SystemEventBlock` 添加 `max-w-full` 约束并将内容断行策略从 `break-words` 改为 `break-all`，解决无空格长字符串溢出。
- **布局层**：`TaskDetail.tsx` 中 CSS Grid 改为 Flex 布局，移除 `layout` 状态（`split`/`main`/`aside`），改为 `asideWidth` 数值状态 + `isDragging` 状态驱动。分割线区域承载悬浮按钮组（hover 显示，拖动隐藏）。
- **交互层**：鼠标拖动实时调整 aside 宽度，最小 48px（保留按钮可见），点击分割线上的 `◀`/`▶` 按钮 toggle 收缩/恢复。

## Tech Stack

- React 19 + TypeScript
- Tailwind CSS v4
- CSS variables（已定义于 `frontend/src/index.css`）

---

## Section 1: 消息超宽修复

### 变更文件

- `frontend/src/pages/tasks/MessageBlocks.tsx`

### 具体改动

**`SystemEventBlock`**（lines 9-18）改为：

```tsx
export function SystemEventBlock({ message }: { message: MessageItem }) {
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-center px-4">
      <div className="flex max-w-full items-center gap-2 rounded-lg border-l-2 border-[var(--apple-blue)] bg-[var(--bg-secondary)] px-3 py-1.5">
        <span className="max-w-full break-all text-xs text-[var(--text-secondary)]">{content}</span>
        <span className="shrink-0 text-xs text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp)}</span>
      </div>
    </div>
  );
}
```

**关键变化**：
- 外层 `div` 添加 `px-4`，给消息两侧留白
- 内层 `div` 添加 `max-w-full`，限制 flex 容器不超出父级宽度
- content `span` 从隐式 `break-words` 改为显式 `break-all`（强制在无空格处断行，解决 JSON 字符串溢出）
- 时间戳 `span` 添加 `shrink-0`，防止被长内容压缩消失

---

## Section 2: 可拖动分割线 + 悬浮按钮组

### 变更文件

- `frontend/src/pages/tasks/TaskDetail.tsx`

### 状态变更

**删除**：
```tsx
type PanelLayout = 'split' | 'main' | 'aside';  // 删除整行
const [layout, setLayout] = useState<PanelLayout>('split');  // 删除整行
```

**新增**（放在组件内部，与现有 hooks 同级）：
```tsx
const MIN_WIDTH = 48;
const DEFAULT_WIDTH = 320;

const [asideWidth, setAsideWidth] = useState(DEFAULT_WIDTH);
const [isDragging, setIsDragging] = useState(false);
const containerRef = useRef<HTMLDivElement>(null);
```

### 拖动逻辑

在组件内部新增处理函数（放在 `const actions = useTaskActions(taskId);` 之后即可）：

```tsx
const handleMouseDown = (e: React.MouseEvent) => {
  e.preventDefault();
  setIsDragging(true);
  const startX = e.clientX;
  const startWidth = asideWidth;

  const onMove = (moveEvent: MouseEvent) => {
    const delta = startX - moveEvent.clientX;
    const newWidth = startWidth + delta;
    const clamped = Math.max(MIN_WIDTH, newWidth);
    if (containerRef.current) {
      const maxWidth = containerRef.current.getBoundingClientRect().width - MIN_WIDTH;
      setAsideWidth(Math.min(maxWidth, clamped));
    }
  };

  const onUp = () => {
    setIsDragging(false);
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
  };

  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
};

const toggleCollapse = (direction: 'left' | 'right') => {
  if (direction === 'left') {
    if (asideWidth <= MIN_WIDTH + 10) {
      setAsideWidth(DEFAULT_WIDTH);
    } else {
      setAsideWidth(MIN_WIDTH);
    }
  } else {
    const container = containerRef.current;
    if (!container) return;
    const maxWidth = container.getBoundingClientRect().width - MIN_WIDTH;
    if (asideWidth >= maxWidth - 10) {
      setAsideWidth(DEFAULT_WIDTH);
    } else {
      setAsideWidth(maxWidth);
    }
  }
};
```

### 布局结构调整

**删除**原有的 grid 容器（lines 134-141）：
```tsx
      <div
        className={[
          'grid min-h-0 flex-1 gap-0 overflow-hidden transition-all duration-300 ease-in-out',
          layout === 'split' && 'lg:grid-cols-[minmax(0,1fr)_320px]',
          layout !== 'split' && 'lg:grid-cols-1',
        ]
          .filter(Boolean)
          .join(' ')}
      >
```

**替换**为 flex 容器：
```tsx
      <div ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden">
```

**删除** main 和 aside 的条件渲染包裹：
- 删除 `{layout !== 'aside' && (` 和对应的 `)}`（lines 143 和 159）
- 删除 `{layout !== 'main' && (` 和对应的 `)}`（lines 162 和 271）

main 和 aside 直接作为 flex 子项，始终渲染。

**main panel**（原 line 144）改为：
```tsx
        <main className="min-h-0 flex-1 flex flex-col bg-[var(--surface)]">
```

**分割线区域**（插在 `main` 和 `aside` 之间）：
```tsx
        <div
          className="group relative w-[6px] shrink-0 cursor-col-resize select-none"
          onMouseDown={handleMouseDown}
        >
          <div className="absolute inset-y-0 left-1/2 w-[1px] -translate-x-1/2 bg-[var(--border)]" />

          <div
            className={[
              'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col gap-1 transition-opacity',
              isDragging ? 'opacity-0' : 'opacity-0 group-hover:opacity-100',
            ].join(' ')}
          >
            <button
              onClick={(e) => { e.stopPropagation(); toggleCollapse('left'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title="Collapse aside"
            >
              ◀
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); toggleCollapse('right'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title="Expand aside"
            >
              ▶
            </button>
          </div>
        </div>
```

**aside panel**（原 line 163）改为：
```tsx
        <aside
          style={{
            width: asideWidth,
            transition: isDragging ? 'none' : 'width 300ms ease-in-out',
          }}
          className="min-h-0 shrink-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-t-0"
        >
```

---

## Section 3: 删除 aside 右上角展开按钮

### 变更文件

- `frontend/src/pages/tasks/TaskDetail.tsx`

### 具体改动

**删除** aside 顶部的按钮和 `justify-between`（lines 164-180 替换）：

原有代码：
```tsx
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.summary')}
              </h2>
              <button
                type="button"
                onClick={() => setLayout(layout === 'aside' ? 'split' : 'aside')}
                className="rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
                aria-label={
                  layout === 'aside'
                    ? t('pages.tasks.collapseSummary')
                    : t('pages.tasks.expandSummary')
                }
              >
                {layout === 'aside' ? '>>' : '<<'}
              </button>
            </div>
```

替换为：
```tsx
            <div className="mb-2">
              <h2 className="text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.summary')}
              </h2>
            </div>
```

**清理**：同时删除 `PanelLayout` 类型定义（line 11）和 `layout` / `setLayout` 相关代码。检查是否还有其他地方引用了 `layout` 变量——确认 `layout` 仅用于 grid 列宽计算和条件渲染，上述改动已完全覆盖。

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/pages/tasks/MessageBlocks.tsx` | 修改 | SystemEventBlock 添加 max-w-full + break-all |
| `frontend/src/pages/tasks/TaskDetail.tsx` | 修改 | Flex 布局替代 Grid，新增拖动 + 悬浮按钮，删除 layout state 和 aside 右上角按钮 |

---

## Self-Review Checklist

- [x] **Placeholder scan**: 无 TBD、TODO。
- [x] **内部一致性**: 拖动逻辑和按钮逻辑互不冲突；最小宽度 48px 确保按钮始终可见。
- [x] **范围检查**: 仅 2 个文件的前端改动，无后端变更。
- [x] **歧义检查**: `break-all` 明确用于无空格 JSON；`toggleCollapse` 的 left/right 行为已在代码中明确。
- [x] **类型一致性**: 未引入新的 TypeScript 类型，仅修改现有组件逻辑。
