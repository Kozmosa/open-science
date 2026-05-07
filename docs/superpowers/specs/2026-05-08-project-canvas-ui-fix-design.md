# Project Canvas UI Bug Fix Design

## Problem

Projects page canvas has multiple layout and interaction issues:

1. **"New Task" button label overflows** — The `Plus` icon and `新建任务` label are not on the same line; text exceeds layout bounds.
2. **Task nodes are not draggable** — Users cannot reposition task blocks on the canvas.
3. **Overall canvas layout is broken** — Nodes, edges, and handles render incorrectly.

## Root Causes

1. **Button component missing flex display** — `Button` base classes do not include `inline-flex` or `flex`. The `gap-1.5` class on the "New Task" button is silently ignored because `gap` only works on flex/grid containers.
2. **Missing React Flow CSS import** — `@xyflow/react/dist/style.css` is never imported. Without React Flow's base stylesheet, node positioning, dragging, edge rendering, and handle styling are all unstyled/broken.
3. **Flex overflow in canvas container** — The ReactFlow wrapper (`<div className="flex-1">`) lacks `min-h-0`, which can cause it to overflow its parent flex column instead of shrinking properly.

## Fix Plan

### 1. Button Component (`frontend/src/components/ui/Button.tsx`)

Add `inline-flex items-center justify-center` to all variant base classes:

```tsx
const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  primary:
    'inline-flex items-center justify-center rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40',
  // ... same for secondary, danger, ghost
};
```

The existing composition `[base, sizeOverride, className]` already puts consumer `className` last, so Tailwind's later-wins override behavior continues to work for padding/text-size overrides.

### 2. React Flow CSS Import (`frontend/src/main.tsx`)

Add the missing base stylesheet import:

```tsx
import '@xyflow/react/dist/style.css';
```

This provides React Flow's required CSS variables and layout rules for nodes, edges, handles, and the drag surface.

### 3. Canvas Container (`frontend/src/components/project/ProjectCanvas.tsx`)

Add `min-h-0` to the ReactFlow wrapper to prevent flex overflow:

```tsx
<div className="flex-1 min-h-0">
```

### 4. TaskNode / Dagre Width Consistency

`TaskNode` uses `min-w-[180px]` while `layoutDagre.ts` uses `NODE_WIDTH = 180`. These are already aligned; no change needed unless visual inspection reveals a mismatch after the CSS import fix.

## Validation

- "New Task" button: icon and label render on a single line with proper gap.
- Canvas: task nodes render at correct positions; edges connect handles.
- Drag: nodes can be dragged and new positions persist to `localStorage`.
- Reset Layout: clears saved positions and re-runs dagre layout.

## Test Plan (post-fix)

1. **Component test for `ProjectCanvas`** — verify React Flow renders nodes without throwing; verify node click callback fires.
2. **Component test for `Button`** — verify icon + label combination renders as a single flex row.
3. **Integration smoke test** — mount `ProjectsPage` with mock data, assert canvas contains expected task nodes.
