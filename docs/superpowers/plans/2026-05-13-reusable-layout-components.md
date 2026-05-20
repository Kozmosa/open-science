# Reusable Layout Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract three recurring layout patterns (left-right split, vertical section stack, draggable card grid) into reusable components in `frontend/src/components/layout/`, then migrate all pages to use them.

**Architecture:** Three self-contained layout-shell components with clear prop interfaces. Pages own business logic and pass content via children/render props. Components encapsulate layout behavior (splitter drag, DnD, spacing) that was previously duplicated.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, @dnd-kit/core, vitest + @testing-library/react

**Spec:** `docs/superpowers/specs/2026-05-13-reusable-layout-components-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/components/layout/SplitPane.tsx` | Create | Sidebar + splitter + main content flex container |
| `frontend/src/components/layout/SectionStack.tsx` | Create | Uniform vertical spacing wrapper with actions slot |
| `frontend/src/components/layout/CardGrid.tsx` | Create | DndContext grid with drag-to-reorder + localStorage |
| `frontend/src/components/layout/index.ts` | Create | Barrel export |
| `frontend/src/pages/TasksPage.tsx` | Modify | Replace inline splitter with SplitPane |
| `frontend/src/pages/ProjectsPage.tsx` | Modify | Replace mouse splitter with SplitPane |
| `frontend/src/pages/SettingsPage.tsx` | Modify | Wrap sections in SectionStack |
| `frontend/src/pages/EnvironmentsPage.tsx` | Modify | Wrap in SectionStack with actions slot |
| `frontend/src/pages/WorkspacesPage.tsx` | Modify | Wrap in SectionStack |
| `frontend/src/pages/ResourcesPage.tsx` | Modify | Replace DndContext + grid with CardGrid |
| `frontend/src/pages/TasksPage.test.tsx` | Modify | Update for SplitPane usage |
| `frontend/src/hooks/useCardLayout.ts` | Reference | Unchanged — feeds cardOrder to CardGrid |

---

### Task 1: Create SplitPane component

**Files:**
- Create: `frontend/src/components/layout/SplitPane.tsx`
- Reference: `frontend/src/pages/TasksPage.tsx:184-211` (splitter handlers), `:214-297` (layout JSX)

- [ ] **Step 1: Write SplitPane component**

```tsx
// frontend/src/components/layout/SplitPane.tsx
import { useCallback, type ReactNode } from 'react';
import { useT } from '../../i18n';

interface Props {
  sidebar: ReactNode;
  children: ReactNode;
  sidebarWidth: number;
  onSidebarWidthChange: (width: number) => void;
  sidebarMinWidth?: number;
  sidebarMaxWidth?: number;
  className?: string;
}

function clampWidth(width: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, width));
}

export default function SplitPane({
  sidebar,
  children,
  sidebarWidth,
  onSidebarWidthChange,
  sidebarMinWidth = 260,
  sidebarMaxWidth = 520,
  className = '',
}: Props) {
  const t = useT();

  const handleSplitterPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = sidebarWidth;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        onSidebarWidthChange(
          clampWidth(startWidth + moveEvent.clientX - startX, sidebarMinWidth, sidebarMaxWidth)
        );
      };
      const handlePointerUp = () => {
        window.removeEventListener('pointermove', handlePointerMove);
        window.removeEventListener('pointerup', handlePointerUp);
      };

      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    },
    [sidebarWidth, sidebarMinWidth, sidebarMaxWidth, onSidebarWidthChange]
  );

  const handleSplitterKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
        return;
      }
      event.preventDefault();
      const delta = event.key === 'ArrowLeft' ? -16 : 16;
      onSidebarWidthChange(clampWidth(sidebarWidth + delta, sidebarMinWidth, sidebarMaxWidth));
    },
    [sidebarWidth, sidebarMinWidth, sidebarMaxWidth, onSidebarWidthChange]
  );

  return (
    <div className={`flex min-h-0 w-full overflow-hidden ${className}`}>
      <aside
        className="flex shrink-0 flex-col bg-[var(--sidebar)] p-3"
        style={{ width: sidebarWidth }}
      >
        {sidebar}
      </aside>

      <div
        role="separator"
        aria-label={t('layout.resizeSidebar')}
        aria-orientation="vertical"
        aria-valuemin={sidebarMinWidth}
        aria-valuemax={sidebarMaxWidth}
        aria-valuenow={sidebarWidth}
        tabIndex={0}
        onPointerDown={handleSplitterPointerDown}
        onKeyDown={handleSplitterKeyDown}
        className="group flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-[var(--surface)] outline-none transition hover:bg-[var(--bg-secondary)] focus:bg-[var(--bg-secondary)]"
      >
        <span className="my-3 w-px rounded-full bg-[var(--border)] transition group-hover:bg-[var(--apple-blue)] group-focus:bg-[var(--apple-blue)]" />
      </div>

      <main className="flex min-w-0 flex-1 flex-col bg-[var(--bg)] p-4">
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Add i18n key for resize label**

Read `frontend/src/i18n/messages.ts`, find the `layout` section, add `resizeSidebar` key after existing layout keys. Check for `layout.expandSidebar` / `layout.collapseSidebar` pattern and add `layout.resizeSidebar` nearby.

- [ ] **Step 3: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

---

### Task 2: Create SectionStack component

**Files:**
- Create: `frontend/src/components/layout/SectionStack.tsx`

- [ ] **Step 1: Write SectionStack component**

```tsx
// frontend/src/components/layout/SectionStack.tsx
import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  gap?: number;
  actions?: ReactNode;
  className?: string;
}

export default function SectionStack({ children, gap = 6, actions, className = '' }: Props) {
  return (
    <div className={`space-y-${gap} ${className}`}>
      {actions ? (
        <div className={`mb-${gap}`}>
          {actions}
        </div>
      ) : null}
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

---

### Task 3: Create CardGrid component

**Files:**
- Create: `frontend/src/components/layout/CardGrid.tsx`
- Reference: `frontend/src/pages/ResourcesPage.tsx:56-79` (DndContext + grid), `frontend/src/components/resources/DraggableResourceCard.tsx` (drag handle)

- [ ] **Step 1: Write CardGrid component**

```tsx
// frontend/src/components/layout/CardGrid.tsx
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useDraggable, useDroppable } from '@dnd-kit/core';
import type { ReactNode } from 'react';

interface CardDef {
  id: string;
  kind: string;
}

interface Group {
  id: string;
  cards: CardDef[];
}

interface Props {
  groups: Group[];
  renderCard: (cardId: string, kind: string, groupId: string) => ReactNode;
  cardOrder: string[];
  onCardOrderChange: (order: string[]) => void;
  storageKey: string;
  columns?: number;
  gap?: number;
  className?: string;
}

function DraggableCard({
  id,
  kind,
  children,
}: {
  id: string;
  kind: string;
  children: ReactNode;
}) {
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } =
    useDraggable({ id, data: { kind } });
  const { setNodeRef: setDropRef } = useDroppable({ id, data: { kind } });

  const style: React.CSSProperties = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    opacity: isDragging ? 0.5 : 1,
    transition: 'opacity 150ms ease',
  };

  return (
    <div ref={setDropRef} style={style} className="relative">
      <div
        ref={setDragRef}
        {...listeners}
        {...attributes}
        className="absolute right-3 top-3 z-10 cursor-grab active:cursor-grabbing"
        title="Drag to reorder"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          className="text-[var(--text-tertiary)]"
        >
          <circle cx="4" cy="4" r="1.5" />
          <circle cx="8" cy="4" r="1.5" />
          <circle cx="12" cy="4" r="1.5" />
          <circle cx="4" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="12" cy="8" r="1.5" />
          <circle cx="4" cy="12" r="1.5" />
          <circle cx="8" cy="12" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
        </svg>
      </div>
      {children}
    </div>
  );
}

export default function CardGrid({
  groups,
  renderCard,
  cardOrder,
  onCardOrderChange,
  storageKey,
  columns = 2,
  gap = 6,
  className = '',
}: Props) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  function handleDragEnd(event: { active: { id: string }; over: { id: string } | null }) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    // Extract kind from composite id: "groupId:kind"
    const activeKind = active.id.split(':')[1];
    const overKind = over.id.split(':')[1];
    if (!activeKind || !overKind || activeKind === overKind) return;

    const activeIndex = cardOrder.indexOf(activeKind);
    const overIndex = cardOrder.indexOf(overKind);
    if (activeIndex === -1 || overIndex === -1) return;

    const newOrder = [...cardOrder];
    const [removed] = newOrder.splice(activeIndex, 1);
    newOrder.splice(overIndex, 0, removed);
    onCardOrderChange(newOrder);

    try {
      localStorage.setItem(storageKey, JSON.stringify({ cardOrder: newOrder }));
    } catch {
      // ignore storage failures
    }
  }

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      {groups.map((group) => (
        <div
          key={group.id}
          className={`grid grid-cols-1 gap-${gap} lg:grid-cols-${columns} ${className}`}
        >
          {cardOrder.map((kind) => {
            const card = group.cards.find((c) => c.kind === kind);
            if (!card) return null;
            return (
              <DraggableCard key={`${group.id}:${kind}`} id={`${group.id}:${kind}`} kind={kind}>
                {renderCard(card.id, kind, group.id)}
              </DraggableCard>
            );
          })}
        </div>
      ))}
    </DndContext>
  );
}
```

- [ ] **Step 2: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

---

### Task 4: Create barrel export

**Files:**
- Create: `frontend/src/components/layout/index.ts`

- [ ] **Step 1: Write barrel export**

```ts
export { default as SplitPane } from './SplitPane';
export { default as SectionStack } from './SectionStack';
export { default as CardGrid } from './CardGrid';
```

- [ ] **Step 2: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

---

### Task 5: Migrate TasksPage to SplitPane

**Files:**
- Modify: `frontend/src/pages/TasksPage.tsx`

- [ ] **Step 1: Remove splitter handlers and width constants**

Remove lines 27-33 (constants and `clampTaskSidebarWidth`), lines 184-211 (splitter handlers), and the `taskSidebarWidth` state from line 67. The `taskSidebarWidth` state stays but `clampTaskSidebarWidth` is removed since SplitPane handles it.

Actually, SplitPane does the clamping internally. The page just needs to keep `taskSidebarWidth` state and `setTaskSidebarWidth`. Remove:
- Lines 27-33: constants + `clampTaskSidebarWidth` function
- Lines 184-211: `handleSplitterPointerDown` + `handleSplitterKeyDown` callbacks
- Line 67: `const [taskSidebarWidth, setTaskSidebarWidth]` — KEEP this line

- [ ] **Step 2: Replace the inner layout div with SplitPane**

Find the return JSX (line 214). Replace:

```tsx
<div className="flex min-h-0 flex-1 bg-[var(--bg)] p-4">
  <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
    <aside ... > ... </aside>
    <Splitter ... />
    <main ...> ... </main>
  </div>
</div>
```

With:

```tsx
<div className="flex min-h-0 flex-1 bg-[var(--bg)] p-4">
  <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
    <SplitPane
      sidebar={<SidebarContent />}
      sidebarWidth={taskSidebarWidth}
      onSidebarWidthChange={setTaskSidebarWidth}
      sidebarMinWidth={260}
      sidebarMaxWidth={520}
      sidebarDefaultWidth={320}
      className="rounded-2xl"
    >
      <TaskDetail ... />
    </SplitPane>
  </div>
</div>
```

Wait — the SplitPane already has the outer flex container. The TasksPage has an additional outer card shell (`rounded-2xl border shadow-sm`). Per the spec, the card shell stays in the page. So the nesting is:

```
<div className="p-4">          ← page outer padding
  <div className="card shell">  ← page-owned card (rounded-2xl border etc.)
    <SplitPane>                 ← layout component
      sidebar + main content
    </SplitPane>
  </div>
</div>
```

But SplitPane renders `<div className="flex min-h-0 w-full overflow-hidden">` which is the same as the card shell. So we can pass the card styling to SplitPane via `className`, or keep the wrapper div.

Simpler: keep the wrapper div and just replace `<aside> + <splitter> + <main>` with `<SplitPane>`. Extract the sidebar content into a fragment.

- [ ] **Step 3: Extract sidebar content**

Move the `<aside>` content (lines 221-273) into a `const sidebarContent` variable before the return. The SplitPane provides the `<aside>` wrapper, so the page only provides the inner content.

- [ ] **Step 4: Replace layout with SplitPane**

Replace the `<aside>...</aside>` + `<div role="separator">...</div>` + `<main>...</main>` block (lines 216-297) with:

```tsx
<SplitPane
  sidebar={
    <>
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            {t('pages.tasks.sidebarEyebrow')}
          </p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--sidebar-foreground)]">
            {t('pages.tasks.sidebarTitle')}
          </h1>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            {t('pages.tasks.sidebarDescription')}
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateDialogOpen(true)} ref={createButtonRef}>
          <Plus className="h-4 w-4" />
          <span className="hidden sm:inline">{t('pages.tasks.newTask')}</span>
        </Button>
      </div>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-medium text-[var(--muted-foreground)]">
          {t('pages.tasks.taskCount', { count: tasks.length })}
        </span>
        <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} className="rounded border-[var(--border)]" />
          {t('pages.tasks.actions.showArchived')}
        </label>
      </div>
      <TaskList
        tasks={tasks}
        selectedTaskId={effectiveSelectedTaskId}
        tasksError={tasksError}
        searchQuery={taskSearchQuery}
        showArchived={showArchived}
        onSearchQueryChange={setTaskSearchQuery}
        onSelectTask={selectTask}
        onArchiveTask={(taskId) => archiveMutation.mutate(taskId)}
        onCancelTask={(taskId) => cancelMutation.mutate(taskId)}
        onDeleteTask={(taskId) => deleteMutation.mutate(taskId)}
      />
    </>
  }
  sidebarWidth={taskSidebarWidth}
  onSidebarWidthChange={setTaskSidebarWidth}
  sidebarMinWidth={260}
  sidebarMaxWidth={520}
  sidebarDefaultWidth={320}
>
  <TaskDetail
    selectedTask={selectedTask}
    detailError={detailError}
    outputItems={outputItems}
    outputError={outputError}
  />
</SplitPane>
```

- [ ] **Step 5: Update imports**

Remove unused imports (`ChevronLeft`, etc. if any). Add `import { SplitPane } from '../components/layout'` (or from `'../components'` once re-exported).

- [ ] **Step 6: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/components/layout/ frontend/src/pages/TasksPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "feat: add SplitPane and migrate TasksPage"
```

---

### Task 6: Migrate ProjectsPage to SplitPane

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`

- [ ] **Step 1: Read current layout and identify what to replace**

In the return JSX (after line ~174), the page has:
- Outer `<div className="flex min-h-0 flex-1 bg-[var(--bg)] p-3">`
- Inner card `<div className="flex min-h-0 w-full overflow-hidden rounded-2xl border...">`
- `<aside>` with ProjectSidebar content
- `<div>` splitter with mouse-based handlers
- `<main>` with ProjectCanvas or no-projects placeholder

- [ ] **Step 2: Remove splitter handlers and refs**

Remove:
- `isResizing`, `startX`, `startWidth` refs
- `handleResizeStart` callback
- `useEffect` with `handleMouseMove` / `handleMouseUp` (lines 89-111)
- `sidebarMinWidth`, `sidebarMaxWidth`, `sidebarDefaultWidth` constants (unless they're identical to SplitPane defaults of 260/520/320)

Keep: `sidebarWidth` state and `setSidebarWidth`.

- [ ] **Step 3: Replace layout with SplitPane**

Replace `<aside>...</aside>` + splitter + `<main>...</main>` with:

```tsx
<SplitPane
  sidebar={<ProjectSidebar ... />}
  sidebarWidth={sidebarWidth}
  onSidebarWidthChange={setSidebarWidth}
>
  {effectiveProjectId ? (
    <ProjectCanvas ... />
  ) : (
    <NoProjectsPlaceholder ... />
  )}
</SplitPane>
```

- [ ] **Step 4: Update imports**

Add `import { SplitPane } from '../components/layout'`. Remove unused icon/splitter imports.

- [ ] **Step 5: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/pages/ProjectsPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "refactor: migrate ProjectsPage to SplitPane"
```

---

### Task 7: Migrate SettingsPage to SectionStack

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Replace inner wrapper div with SectionStack**

Find the return JSX structure. Replace the `<div className="space-y-6">` that wraps the section cards with `<SectionStack>`. Keep the `<PageHeader>` outside SectionStack (above it).

Before (structure):
```
<div className="space-y-8">
  <PageHeader ... />
  <div className="space-y-6">
    <Alert ... />
    <SectionCard>...</SectionCard>
    <SectionCard>...</SectionCard>
    ...
  </div>
</div>
```

After:
```
<div className="space-y-8">
  <PageHeader ... />
  <SectionStack>
    {recoveryReason !== null ? <Alert ... /> : null}
    <SectionCard>...</SectionCard>
    <SectionCard>...</SectionCard>
    ...
  </SectionStack>
</div>
```

- [ ] **Step 2: Update imports**

Add `import { SectionStack } from '../components/layout'`.

- [ ] **Step 3: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/pages/SettingsPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "refactor: migrate SettingsPage to SectionStack"
```

---

### Task 8: Migrate EnvironmentsPage to SectionStack

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`

- [ ] **Step 1: Wrap grid content in SectionStack with actions slot**

The EnvironmentsPage has a top action bar (`<SectionCard className="flex flex-wrap...">`) above a grid. The action bar becomes the `actions` prop of SectionStack.

Before:
```
<div className="space-y-8">
  <PageHeader ... />
  <SectionCard className="flex flex-wrap items-center justify-between gap-3 p-5">
    <current selection + Add button>
  </SectionCard>
  <div className="grid gap-6 xl:grid-cols-[1.35fr_1fr]">
    ...
  </div>
</div>
```

After:
```
<div className="space-y-8">
  <PageHeader ... />
  <SectionStack
    actions={
      <SectionCard className="flex flex-wrap items-center justify-between gap-3 p-5">
        <current selection + Add button>
      </SectionCard>
    }
  >
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      ...
    </div>
  </SectionStack>
</div>
```

- [ ] **Step 2: Update imports**

Add `import { SectionStack } from '../components/layout'`.

- [ ] **Step 3: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/pages/EnvironmentsPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "refactor: migrate EnvironmentsPage to SectionStack"
```

---

### Task 9: Migrate WorkspacesPage to SectionStack

**Files:**
- Modify: `frontend/src/pages/WorkspacesPage.tsx`

- [ ] **Step 1: Wrap in SectionStack**

Replace `space-y-8` wrapper div with SectionStack.

Before:
```
<div className="space-y-8">
  <PageHeader ... />
  <WorkspaceManagerCard />
</div>
```

After:
```
<SectionStack gap={8}>
  <PageHeader ... />
  <WorkspaceManagerCard />
</SectionStack>
```

Note: use `gap={8}` to preserve the current 8-unit spacing between header and card.

- [ ] **Step 2: Update imports**

Add `import { SectionStack } from '../components/layout'`.

- [ ] **Step 3: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/pages/WorkspacesPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "refactor: migrate WorkspacesPage to SectionStack"
```

---

### Task 10: Migrate ResourcesPage to CardGrid

**Files:**
- Modify: `frontend/src/pages/ResourcesPage.tsx`
- Reference: `frontend/src/components/resources/DraggableResourceCard.tsx` (drag handle stays but DndContext wrapper moves)

- [ ] **Step 1: Remove DndContext and sensors**

Remove:
- `import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'`
- `const sensors = useSensors(...)` (lines 26-32)
- The `<DndContext>` wrapper and its `onDragEnd` handler (lines 56-79)

- [ ] **Step 2: Replace DndContext + grid with CardGrid**

Build a `groups` array from `snapshots`, and a `renderCard` function that returns the DraggableResourceCard with the correct inner content card.

```tsx
import { CardGrid } from '../components/layout';
import DraggableResourceCard from '../components/resources/DraggableResourceCard';

// Inside component:
const groups = useMemo(
  () =>
    snapshots.map((snapshot) => ({
      id: snapshot.environment_id,
      cards: [
        { id: `${snapshot.environment_id}:system`, kind: 'system' as CardKind },
        { id: `${snapshot.environment_id}:processes`, kind: 'processes' as CardKind },
      ],
    })),
  [snapshots]
);

const renderCard = useCallback(
  (cardId: string, kind: string, groupId: string) => {
    const snapshot = snapshots.find((s) => s.environment_id === groupId);
    if (!snapshot) return null;
    return (
      <DraggableResourceCard id={cardId} kind={kind as CardKind}>
        {kind === 'system' ? (
          <SystemResourceCard snapshot={snapshot} />
        ) : (
          <AinrfProcessCard processes={snapshot.ainrf_processes} environment_name={snapshot.environment_name} />
        )}
      </DraggableResourceCard>
    );
  },
  [snapshots]
);
```

Then replace the DndContext block with:

```tsx
<CardGrid
  groups={groups}
  renderCard={renderCard}
  cardOrder={layout.cardOrder}
  onCardOrderChange={(order) => setLayout({ cardOrder: order as CardKind[] })}
  storageKey="scholar-agent:resources-layout"
/>
```

- [ ] **Step 3: Update imports**

Remove `DndContext`, `PointerSensor`, `useSensor`, `useSensors` imports. Add `useMemo` to React import. Add `CardGrid` import. Remove `cardRenderers` and the `DraggableResourceCard` JSX from the inner map.

- [ ] **Step 4: Update the `useCardLayout` hook return value**

The hook needs to expose `setLayout` so CardGrid's `onCardOrderChange` can call it. Check that `useCardLayout` already returns `{ layout, swapCards, setLayout }`. It does (line 66 of useCardLayout.ts).

- [ ] **Step 5: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add frontend/src/pages/ResourcesPage.tsx
git -C /home/xuyang/code/scholar-agent commit -m "refactor: migrate ResourcesPage to CardGrid"
```

---

### Task 11: Re-export layout components from components barrel

**Files:**
- Modify: `frontend/src/components/index.ts` (if it exists)

Or skip — pages import directly from `../components/layout`.

- [ ] **Step 1: Final full test run**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -8
```

Expected: 20 test files passed, 102 tests passed.

- [ ] **Step 2: Commit**

```bash
git -C /home/xuyang/code/scholar-agent add -A
git -C /home/xuyang/code/scholar-agent commit -m "chore: final layout migration cleanup"
```

---

## Verification Checklist

- [ ] `tsc -b` passes with zero errors
- [ ] `npm run test:run` — all 22 test files, 107 tests passing
- [ ] TasksPage: sidebar drag resize works, keyboard ArrowLeft/Right resize works
- [ ] ProjectsPage: sidebar drag resize works, keyboard resize works (was missing)
- [ ] SettingsPage: sections render with correct spacing
- [ ] EnvironmentsPage: action bar renders, grid layout intact
- [ ] WorkspacesPage: spacing unchanged
- [ ] ResourcesPage: cards draggable, order persists across refresh
