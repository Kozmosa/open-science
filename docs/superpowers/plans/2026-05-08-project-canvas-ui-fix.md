# Project Canvas UI Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix layout and interaction bugs on the Projects page canvas: broken "New Task" button alignment, missing drag support, and incorrect canvas layout.

**Architecture:** Three targeted fixes: (1) Add `inline-flex` to `Button` so `gap-*` works, (2) Import React Flow's base CSS so nodes/edges/dragging render correctly, (3) Add `min-h-0` to the canvas flex container to prevent overflow. Follow each fix with component-level tests.

**Tech Stack:** React 19 + TypeScript + Tailwind CSS v4, `@xyflow/react`, Vitest + jsdom + `@testing-library/react`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/components/ui/Button.tsx` | Modify | Add `inline-flex items-center justify-center` to all variant base classes |
| `frontend/src/main.tsx` | Modify | Import `@xyflow/react/dist/style.css` after `./index.css` |
| `frontend/src/components/project/ProjectCanvas.tsx` | Modify | Add `min-h-0` to ReactFlow wrapper div |
| `frontend/src/components/ui/Button.test.tsx` | Create | Verify Button renders with flex layout classes |
| `frontend/src/components/project/ProjectCanvas.test.tsx` | Create | Verify ProjectCanvas mounts React Flow without throwing; nodes render from props |

---

### Task 1: Fix Button Flex Layout + Add Test

**Files:**
- Modify: `frontend/src/components/ui/Button.tsx`
- Create: `frontend/src/components/ui/Button.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ui/Button.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Plus } from 'lucide-react';
import Button from './Button';

describe('Button', () => {
  it('renders as an inline-flex container so gap works for icon + label', () => {
    render(
      <Button className="gap-1.5">
        <Plus size={14} data-testid="icon" />
        <span>New Task</span>
      </Button>
    );

    const button = screen.getByRole('button');
    expect(button).toHaveClass('inline-flex');
    expect(button).toHaveClass('items-center');
    expect(button).toHaveClass('justify-center');
    expect(button).toHaveClass('gap-1.5');
    expect(screen.getByTestId('icon')).toBeInTheDocument();
    expect(screen.getByText('New Task')).toBeInTheDocument();
  });

  it('allows consumer className to override base padding and text size', () => {
    render(<Button className="px-3 text-xs">Label</Button>);
    const button = screen.getByRole('button');
    // Consumer className comes last, so Tailwind later-wins applies
    expect(button).toHaveClass('px-3');
    expect(button).toHaveClass('text-xs');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ui/Button.test.tsx`

Expected: FAIL — `inline-flex` not found in button classes.

- [ ] **Step 3: Fix Button component**

Modify `frontend/src/components/ui/Button.tsx`. Update `variantClasses` to add `inline-flex items-center justify-center` to every variant:

```tsx
const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  primary:
    'inline-flex items-center justify-center rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40',
  secondary:
    'inline-flex items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:cursor-not-allowed disabled:opacity-40',
  danger:
    'inline-flex items-center justify-center rounded-lg bg-[#ff3b30] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#d32f2f] disabled:cursor-not-allowed disabled:opacity-40',
  ghost:
    'inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-40',
};
```

No other changes needed — the existing `[base, sizeOverride, className].join(' ')` composition already puts consumer `className` last.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ui/Button.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/Button.tsx frontend/src/components/ui/Button.test.tsx
git commit -m "fix(ui): add inline-flex to Button so gap works for icon+label

- Add inline-flex items-center justify-center to all variant base classes
- Consumer className still overrides via Tailwind later-wins behavior
- Add Button.test.tsx verifying flex layout and className overrides

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Import React Flow CSS + Fix Canvas Container

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/components/project/ProjectCanvas.tsx`

- [ ] **Step 1: Add React Flow base CSS import**

Modify `frontend/src/main.tsx`. Add the import immediately after `./index.css`:

```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import '@xyflow/react/dist/style.css';
import App from './App.tsx';
import { LocaleProvider } from './i18n';
```

- [ ] **Step 2: Add min-h-0 to canvas wrapper**

Modify `frontend/src/components/project/ProjectCanvas.tsx`. Find the ReactFlow wrapper div and add `min-h-0`:

```tsx
<div className="flex-1 min-h-0">
```

The relevant section (around line 181-196):

```tsx
<div className="flex-1 min-h-0">
  {tasks.length === 0 ? (
    <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
      {t('pages.projects.emptyCanvas')}
    </div>
  ) : (
    <ReactFlowProvider>
      <CanvasInner
        projectId={projectId}
        tasks={tasks}
        edges={edges}
        onNodeClick={onNodeClick}
      />
    </ReactFlowProvider>
  )}
</div>
```

- [ ] **Step 3: Verify type check passes**

Run: `cd frontend && node_modules/.bin/tsc -b`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.tsx frontend/src/components/project/ProjectCanvas.tsx
git commit -m "fix(ui): import React Flow CSS and fix canvas flex overflow

- Import @xyflow/react/dist/style.css in main.tsx (required for nodes,
  edges, handles, and drag interactions to render correctly)
- Add min-h-0 to ReactFlow wrapper to prevent flex overflow in column layout

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Add ProjectCanvas Component Test

**Files:**
- Create: `frontend/src/components/project/ProjectCanvas.test.tsx`

- [ ] **Step 1: Write the test**

Create `frontend/src/components/project/ProjectCanvas.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProjectCanvas from './ProjectCanvas';
import type { TaskSummary, TaskEdge } from '../../types';

// Mock React Flow sub-components that depend on browser APIs not available in jsdom
vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>('@xyflow/react');
  return {
    ...actual,
    ReactFlow: ({ children, nodes }: { children?: React.ReactNode; nodes?: unknown[] }) => (
      <div data-testid="react-flow">
        {nodes ? <div data-testid="node-count">{nodes.length}</div> : null}
        {children}
      </div>
    ),
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Background: () => <div data-testid="background" />,
    Controls: () => <div data-testid="controls" />,
    MiniMap: () => <div data-testid="minimap" />,
  };
});

const mockTasks: TaskSummary[] = [
  {
    task_id: 't1',
    title: 'Task One',
    status: 'running',
    created_at: '2026-05-08T10:00:00Z',
    updated_at: '2026-05-08T10:00:00Z',
    workspace_summary: { workspace_id: 'w1', label: 'WS1' },
    environment_summary: { id: 'e1', alias: 'env1', display_name: 'Env One' },
  },
];

const mockEdges: TaskEdge[] = [];

describe('ProjectCanvas', () => {
  it('renders empty canvas placeholder when no tasks', () => {
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={[]}
        edges={[]}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
      />
    );

    expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    expect(screen.getByText("Click 'New Task' to get started")).toBeInTheDocument();
  });

  it('renders nodes when tasks are provided', () => {
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={mockTasks}
        edges={mockEdges}
        onNodeClick={vi.fn()}
        onNewTask={vi.fn()}
        onResetLayout={vi.fn()}
      />
    );

    expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    expect(screen.getByTestId('node-count')).toHaveTextContent('1');
  });

  it('calls onNewTask when New Task button is clicked', () => {
    const onNewTask = vi.fn();
    render(
      <ProjectCanvas
        projectId="p1"
        tasks={mockTasks}
        edges={mockEdges}
        onNodeClick={vi.fn()}
        onNewTask={onNewTask}
        onResetLayout={vi.fn()}
      />
    );

    const newTaskButton = screen.getByText('New Task');
    newTaskButton.click();
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && npx vitest run src/components/project/ProjectCanvas.test.tsx`

Expected: PASS — all three assertions pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/project/ProjectCanvas.test.tsx
git commit -m "test(ui): add ProjectCanvas component tests

- Verify empty canvas placeholder renders
- Verify nodes are passed to React Flow from tasks prop
- Verify New Task button fires onNewTask callback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Full Verification

**Files:** None (validation only)

- [ ] **Step 1: Run all frontend tests**

Run: `cd frontend && npx vitest run`

Expected: All tests pass, including the new `Button.test.tsx` and `ProjectCanvas.test.tsx`.

- [ ] **Step 2: Run type check**

Run: `cd frontend && node_modules/.bin/tsc -b`

Expected: No type errors.

- [ ] **Step 3: Run lint check**

Run: `cd frontend && npm run lint`

Expected: No lint errors in modified files.

- [ ] **Step 4: Final verification summary**

Confirm all of the following visually or via tests:

| Check | Expected Result |
|-------|----------------|
| Button `gap-*` | Icon and label on same row with gap |
| React Flow CSS | Nodes have correct position, edges connect handles |
| Drag interaction | Nodes can be dragged; positions save to localStorage |
| Canvas flex | Canvas fills available height without overflow |
| Tests | `Button.test.tsx` + `ProjectCanvas.test.tsx` pass |
| Types | `tsc -b` passes |

No additional commit needed if all passes.

---

## Self-Review

**Spec coverage:**
- Button flex fix → Task 1
- React Flow CSS import → Task 2 Step 1
- Canvas container `min-h-0` → Task 2 Step 2
- Button test → Task 1
- ProjectCanvas test → Task 3

**Placeholder scan:** No TBD/TODO/fill-in-details found.

**Type consistency:** All type names (`TaskSummary`, `TaskEdge`) match the existing codebase imports. Mock types in test align with actual component props.
