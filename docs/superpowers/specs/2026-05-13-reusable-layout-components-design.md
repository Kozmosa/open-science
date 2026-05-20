# Design Spec: Reusable Layout Components

## Context

The AINRF frontend has three recurring layout patterns implemented with duplicated
code across multiple pages. Each instance has its own quirks (different splitter
implementations, different spacing values, one-off DndContext setups). This spec
defines three reusable layout-shell components that encapsulate layout structure
while letting pages own their business logic.

## Components

### 1. SplitPane — resizable left-right split layout

**File:** `frontend/src/components/layout/SplitPane.tsx`

```
┌─────────────────────────────────────────────┐
│ ┌──────────┬──┬──────────────────────────┐ │
│ │ Sidebar   │▓▓│     Main Content         │ │
│ │           │  │     (children)           │ │
│ └──────────┴──┴──────────────────────────┘ │
└─────────────────────────────────────────────┘
```

Props:

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `sidebar` | `ReactNode` | required | sidebar content |
| `children` | `ReactNode` | required | main content area |
| `sidebarWidth` | `number` | required | controlled width px |
| `onSidebarWidthChange` | `(w: number) => void` | required | clamped width callback |
| `sidebarMinWidth` | `number` | `260` | |
| `sidebarMaxWidth` | `number` | `520` | |
| `sidebarDefaultWidth` | `number` | `320` | |
| `className` | `string` | `''` | appended to outer container |

Built-in behavior (from TasksPage's current implementation):
- Pointer-event splitter handle (`onPointerDown` → `pointermove/pointerup` on window)
- Keyboard resize: ArrowLeft (-16px), ArrowRight (+16px), both clamped
- Full ARIA: `role="separator"`, `aria-orientation="vertical"`, `aria-label`, `aria-valuemin/max/now`
- Visual: hover/focus turns handle line `var(--apple-blue)`, splitter bg transitions
- Sidebar: `flex shrink-0 flex-col bg-[var(--sidebar)] p-3`, width via inline style
- Main: `flex min-w-0 flex-1 flex-col bg-[var(--bg)] p-4`

Replaces: TasksPage splitter code (lines ~168-211), ProjectsPage splitter code (lines ~81-111).

### 2. SectionStack — uniform vertical section layout

**File:** `frontend/src/components/layout/SectionStack.tsx`

```
┌─────────────────────────────────────┐
│ slot: actions                       │  ← optional (e.g. "Add" button bar)
├─────────────────────────────────────┤
│   children[0]                       │
│          ↕ gap (default 6)          │
│   children[1]                       │
│          ↕ gap                      │
│   ...                               │
└─────────────────────────────────────┘
```

Props:

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `children` | `ReactNode` | required | SectionCards or any content |
| `gap` | `number` | `6` | Tailwind `space-y-{n}` value |
| `actions` | `ReactNode` | — | top action bar slot |
| `className` | `string` | `''` | appended to outer container |

Behavior:
- Renders `<div className="space-y-{gap}">` wrapping children
- If `actions` is provided, renders it above children with `mb-{gap}` separator
- No PageHeader — pages render their own PageHeader above SectionStack
- SectionCard remains a standalone component; not absorbed into SectionStack

Replaces: `space-y-8`/`space-y-6` wrapper divs in SettingsPage, EnvironmentsPage, WorkspacesPage.

### 3. CardGrid — draggable card grid with order persistence

**File:** `frontend/src/components/layout/CardGrid.tsx`

Props:

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `groups` | `{ id: string; cards: CardDef[] }[]` | required | rows of cards |
| `renderCard` | `(cardId, kind, groupId) => ReactNode` | required | card content renderer |
| `cardOrder` | `string[]` | required | controlled kind order |
| `onCardOrderChange` | `(order: string[]) => void` | required | |
| `storageKey` | `string` | required | localStorage key |
| `columns` | `number` | `2` | grid columns (lg breakpoint) |
| `gap` | `number` | `6` | gap between cards |
| `className` | `string` | `''` | appended to outer container |

Where: `CardDef = { id: string; kind: string }`

Built-in behavior:
- DndContext with PointerSensor (8px activation distance)
- Each card is both drag source and drop target
- Drag handle: 9-dot SVG grid in top-right corner
- Visual: opacity 0.5 while dragging, 150ms ease
- localStorage persistence: reads on mount, writes on reorder, validates shape, falls back to default on corruption
- Grid: `grid grid-cols-1 gap-{n} lg:grid-cols-{columns}`

Replaces: ResourcesPage DndContext + grid rendering (lines ~56-79), DraggableResourceCard wrapper logic.

## File Structure

```
frontend/src/components/layout/
  SplitPane.tsx
  SectionStack.tsx
  CardGrid.tsx
  index.ts
```

New directory: `components/layout/` — parallel to existing `components/common/`, `components/ui/`, `components/resources/`, etc.

## Migration Plan

### Phase 1: Create components (no existing code changes)
1. Create `SplitPane` with TasksPage's splitter logic (pointer + keyboard + ARIA)
2. Create `SectionStack`
3. Create `CardGrid`
4. Export from `index.ts`

### Phase 2: Migrate pages
1. **TasksPage** — replace splitter div + handlers with `<SplitPane>`, remove `handleSplitterPointerDown`, `handleSplitterKeyDown`, width clamping
2. **ProjectsPage** — same, replace mouse-based splitter with `<SplitPane>`
3. **SettingsPage** — wrap sections in `<SectionStack>`
4. **EnvironmentsPage** — wrap in `<SectionStack actions={...}>`
5. **WorkspacesPage** — wrap in `<SectionStack>`
6. **ResourcesPage** — replace DndContext + grid with `<CardGrid>`

### Phase 3: Clean up
- Remove unused splitter/width state from pages
- Update tests for migrated pages

## What Does NOT Change

- Page-level business logic (task selection, environment queries, etc.)
- SectionCard component — stays independent
- PageHeader component — stays independent, rendered by pages above SectionStack
- `useCardLayout` hook — consumed by ResourcesPage, feeds `cardOrder` to CardGrid
- `DraggableResourceCard` — content cards stay; only the DndContext wrapper moves into CardGrid

## Verification

1. Type check: `cd frontend && node_modules/.bin/tsc -b`
2. Tests: `npm run test:run` (all 107 tests must pass)
3. Manual check per page:
   - TasksPage: sidebar drag/arrow-key resize, task selection, create/archive/delete
   - ProjectsPage: sidebar drag/arrow-key resize, canvas interaction
   - SettingsPage: section collapse/expand, spacing unchanged
   - EnvironmentsPage: action bar renders, grid layout intact
   - WorkspacesPage: layout unchanged
   - ResourcesPage: cards draggable, order persists across refresh
