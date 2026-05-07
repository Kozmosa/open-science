# TaskDetail MetadataRow UI Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix text overflow and alignment issues in the TaskDetail sidebar MetadataRow component.

**Architecture:** Pure CSS fix within a single React component. Replace `justify-between` layout with fixed-width label + flexible truncated value.

**Tech Stack:** React, Tailwind CSS, TypeScript

---

### Task 1: Modify MetadataRow Component

**Files:**
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx:13-30`

- [ ] **Step 1: Apply the layout fix**

  In `frontend/src/pages/tasks/TaskDetail.tsx`, update the `MetadataRow` component:

  ```tsx
  function MetadataRow({
    label,
    value,
    fallback,
  }: {
    label: string;
    value: string | number | null;
    fallback: string;
  }) {
    return (
      <div className="flex items-start gap-4 border-b border-[var(--border)] py-2 last:border-0">
        <span className="w-28 shrink-0 text-xs text-[var(--text-secondary)]">{label}</span>
        <span className="min-w-0 flex-1 truncate text-right text-xs font-medium text-[var(--text)]">
          {value ?? fallback}
        </span>
      </div>
    );
  }
  ```

  Changes made:
  - Container: `justify-between` → `gap-4` (fixed gap instead of space-between)
  - Label: added `w-28 shrink-0` (112px fixed width, prevent shrinking)
  - Value: `max-w-[70%]` → `min-w-0 flex-1 truncate` (fill remaining space, truncate overflow)

- [ ] **Step 2: Run frontend type check**

  ```bash
  cd frontend && node_modules/.bin/tsc -b
  ```

  Expected: No TypeScript errors.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/pages/tasks/TaskDetail.tsx
  git commit -m "$(cat <<'EOF'
  fix: prevent text overflow and align MetadataRow labels in TaskDetail

  - Replace justify-between with fixed-width labels (w-28) + flex-1 values
  - Add truncate to value spans to prevent overflow on long paths/commands
  - Values now align consistently across all rows in sidebar cards

  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2: Verify the Fix

**Files:**
- None (runtime verification)

- [ ] **Step 1: Start the frontend dev server**

  ```bash
  cd frontend && npm run dev
  ```

  Wait for "ready in" message. Note the localhost port (usually `5173`).

- [ ] **Step 2: Open the Tasks page in browser**

  Navigate to `http://localhost:<port>/tasks` and select a task with long metadata values (e.g., a task with a long `resolved_workdir`, `snapshot_path`, or `command`).

- [ ] **Step 3: Verify the fix visually**

  Check the right sidebar cards (Summary, Binding, Runtime, Result):

  1. **Alignment**: All labels (left column) should have the same width; all values (right column) should start at the same horizontal position.
  2. **Overflow**: Long values should display with an ellipsis (`...`) at the end instead of breaking the card boundary.
  3. **No regression**: Short values should still be right-aligned within their column.

- [ ] **Step 4: Stop the dev server**

  Press `Ctrl+C` in the terminal running the dev server.

---

## Self-Review

**1. Spec coverage:**
- ✅ Fixed-width labels (w-28 shrink-0) → Task 1 Step 1
- ✅ Truncate overflow (truncate class) → Task 1 Step 1
- ✅ Value fills remaining space (flex-1) → Task 1 Step 1
- ✅ Visual verification in browser → Task 2

**2. Placeholder scan:**
- No TBD/TODO/fill-in-later patterns found.
- All code blocks contain complete, copy-pasteable code.
- All commands include expected output.

**3. Type consistency:**
- Component props and types unchanged; only CSS classes modified. No type mismatches.
