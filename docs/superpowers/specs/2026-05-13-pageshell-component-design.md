# Design Spec: PageShell Component

## Context

Four pages use the SplitPane left-right layout (TasksPage, ProjectsPage,
WorkspacesPage, FileBrowserPage), but each has a different outer container
— different padding values, some with a card shell and some without.

This spec adds a PageShell wrapper component that standardizes the outer
layout across all split-pane pages, using TasksPage's pattern as the baseline.

## Component

### PageShell

**File:** `frontend/src/components/layout/PageShell.tsx`

A page-level wrapper that provides uniform outer padding and a card container.

Props:

| Prop | Type | Default | Notes |
|------|------|---------|-------|
| `children` | `ReactNode` | required | page content (SplitPane etc.) |
| `className` | `string` | `''` | appended to outer container |

Renders:

```tsx
<div className="flex min-h-0 flex-1 bg-[var(--bg)] p-4">
  <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
    {children}
  </div>
</div>
```

### Barrel export update

Add `PageShell` to `frontend/src/components/layout/index.ts`.

## Migration

Each page changes to:

```tsx
<PageShell>
  <SplitPane sidebar={...} sidebarWidth={...} onSidebarWidthChange={...}>
    {main content}
  </SplitPane>
</PageShell>
```

| Page | Before | After |
|------|--------|-------|
| TasksPage | `<div p-4><div card> <SplitPane>` | `<PageShell><SplitPane>` |
| ProjectsPage | `<div p-3><SplitPane>` | `<PageShell><SplitPane>` |
| WorkspacesPage | `<SplitPane>` | `<PageShell><SplitPane>` |
| FileBrowserPage | `<div no-padding><SplitPane>` | `<PageShell><SplitPane>` |

## What Does NOT Change

- SplitPane internal structure and behavior
- Page business logic
- SectionCard, SectionStack, CardGrid components

## Verification

1. Type check: `cd frontend && node_modules/.bin/tsc -b`
2. Tests: `npm run test:run` (all tests pass)
3. Visual: all four pages have identical outer padding and card styling
