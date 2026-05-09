# TaskDetail Interactions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix message overflow in SystemEventBlock, replace static grid layout with a resizable flex splitter, and move panel toggle buttons from the aside header to a hover-reveal button group on the splitter.

**Architecture:** Two-file frontend change. Task 1 is a single-component fix in MessageBlocks. Task 2 is a larger refactor in TaskDetail: delete the `layout` state and Grid layout, introduce `asideWidth` + `isDragging` state, implement mouse-drag width adjustment, add a splitter with hover-reveal collapse buttons, and remove the old `<<`/`>>` toggle button.

**Tech Stack:** React 19 + TypeScript, Tailwind CSS v4, CSS variables

---

### Task 1: Fix SystemEventBlock overflow

**Files:**
- Modify: `frontend/src/pages/tasks/MessageBlocks.tsx`

- [ ] **Step 1: Replace SystemEventBlock implementation**

Find `SystemEventBlock` (lines 9-18) and replace with:

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

Key changes:
- Outer `div` adds `px-4` for side padding
- Inner `div` adds `max-w-full` to constrain width
- Content `span` uses `break-all` instead of implicit `break-words`
- Timestamp `span` adds `shrink-0`

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/tasks/MessageBlocks.tsx
git commit -m "fix(ui): prevent SystemEventBlock overflow with break-all and max-w-full"
```

---

### Task 2: Resizable splitter layout in TaskDetail

**Files:**
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

- [ ] **Step 1: Delete PanelLayout type and layout state**

Delete line 11:
```tsx
type PanelLayout = 'split' | 'main' | 'aside';
```

Delete line 49:
```tsx
const [layout, setLayout] = useState<PanelLayout>('split');
```

- [ ] **Step 2: Add new state and refs**

Add the following after line 53 (`const { messages } = useTaskMessages(taskId, outputItems);`):

```tsx
const MIN_WIDTH = 48;
const DEFAULT_WIDTH = 320;

const [asideWidth, setAsideWidth] = useState(DEFAULT_WIDTH);
const [isDragging, setIsDragging] = useState(false);
const containerRef = useRef<HTMLDivElement>(null);
```

Also add `useRef` to the existing React import on line 1:
```tsx
import { useRef, useState } from 'react';
```

- [ ] **Step 3: Add drag and toggle handlers**

Add the following after line 54 (`const actions = useTaskActions(taskId);`):

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

- [ ] **Step 4: Replace grid container with flex container**

Find and delete lines 134-141 (the grid container div with conditional grid-cols):

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

Replace with:
```tsx
      <div ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden">
```

- [ ] **Step 5: Remove conditional rendering around main and aside**

Delete line 143:
```tsx
        {layout !== 'aside' && (
```

Delete line 159 (the closing `)}` after `</main>`).

Delete line 162:
```tsx
        {layout !== 'main' && (
```

Delete line 271 (the closing `)}` after `</aside>`).

Both `main` and `aside` are now direct children of the flex container, always rendered.

- [ ] **Step 6: Update main element**

Change line 144 from:
```tsx
          <main className="min-h-0 flex flex-col bg-[var(--surface)]">
```
to:
```tsx
        <main className="min-h-0 flex-1 flex flex-col bg-[var(--surface)]">
```

- [ ] **Step 7: Insert splitter between main and aside**

After the closing `</main>` tag, insert the splitter div:

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

- [ ] **Step 8: Update aside element**

Change the `<aside>` opening tag from:
```tsx
          <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-l lg:border-t-0">
```
to:
```tsx
        <aside
          style={{
            width: asideWidth,
            transition: isDragging ? 'none' : 'width 300ms ease-in-out',
          }}
          className="min-h-0 shrink-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-t-0"
        >
```

- [ ] **Step 9: Remove old toggle button from aside header**

Find and replace lines 164-180 (the aside header with `justify-between` and the `<<`/`>>` button):

From:
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

To:
```tsx
            <div className="mb-2">
              <h2 className="text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.summary')}
              </h2>
            </div>
```

- [ ] **Step 10: Clean up unused imports and aria-label translations**

The `useT()` hook is still needed for other translations. The `aria-label` translations `pages.tasks.collapseSummary` and `pages.tasks.expandSummary` in `messages.ts` are no longer used by this component. They can be left in place (no harm) or removed in a separate cleanup. For this task, leave them.

- [ ] **Step 11: Verify TypeScript compiles**

Run:
```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/pages/tasks/TaskDetail.tsx
git commit -m "feat(ui): resizable splitter with hover-reveal collapse buttons, remove layout toggle"
```

---

### Task 3: Final verification

- [ ] **Step 1: Run full frontend type check**

```bash
cd /home/xuyang/code/scholar-agent/.claude/worktrees/feat+agent-sdk-engine/frontend && node_modules/.bin/tsc -b
```

Expected: No errors.

- [ ] **Step 2: Verify no leftover layout references**

Search for leftover `layout` or `setLayout` usage in TaskDetail:

```bash
grep -n 'layout\|setLayout\|PanelLayout' frontend/src/pages/tasks/TaskDetail.tsx || echo "No leftover layout references"
```

Expected: "No leftover layout references" (the only exception might be `layout` used in CSS class names like `lg:grid-cols-1` which we already removed).

- [ ] **Step 3: Verify file structure**

Confirm both modified files are clean:

```bash
git diff --stat HEAD~2..HEAD
```

Expected: Only `MessageBlocks.tsx` and `TaskDetail.tsx` changed.

---

## Self-Review

**1. Spec coverage:**
- Message overflow fix (`break-all` + `max-w-full`) → Task 1
- Draggable splitter → Task 2 Steps 2, 4, 7
- Hover-reveal buttons → Task 2 Step 7
- Delete old toggle button → Task 2 Step 9
- Remove `layout` state → Task 2 Steps 1, 5
- Flex layout replacing Grid → Task 2 Steps 4, 6, 8

**2. Placeholder scan:** No TBD, TODO, or vague instructions found.

**3. Type consistency:** `asideWidth` is `number` throughout. `containerRef` is `RefObject<HTMLDivElement>`. `toggleCollapse` parameter is `'left' | 'right'`.
