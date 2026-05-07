# Task Detail Panel Collapse/Expand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add collapse/expand buttons to the TaskDetail page so users can focus on either the output timeline or the summary sidebar.

**Architecture:** A single `useState` in `TaskDetail` manages the layout mode (`split` | `main` | `aside`). Grid class names and conditional rendering switch the visible panel. Transition animation is handled by `transition-all duration-300` on the grid container.

**Tech Stack:** React, Tailwind CSS, TypeScript

---

### Task 1: Add Layout State and Grid Switching

**Files:**
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

- [ ] **Step 1: Import `useState`**

  Add to the imports at the top of `frontend/src/pages/tasks/TaskDetail.tsx`:

  ```tsx
  import { useState } from 'react';
  ```

- [ ] **Step 2: Add layout state**

  Inside the `TaskDetail` component (after `const t = useT();`), add:

  ```tsx
  const [layout, setLayout] = useState<'split' | 'main' | 'aside'>('split');
  ```

- [ ] **Step 3: Replace the grid container with dynamic classes**

  Find line 93 (the grid container):

  ```tsx
  <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
  ```

  Replace it with:

  ```tsx
  <div
    className={[
      'grid min-h-0 flex-1 gap-0 overflow-hidden transition-all duration-300 ease-in-out',
      layout === 'split' && 'lg:grid-cols-[minmax(0,1fr)_320px]',
      layout === 'main' && 'lg:grid-cols-[1fr_0fr]',
      layout === 'aside' && 'lg:grid-cols-[0fr_1fr]',
    ]
      .filter(Boolean)
      .join(' ')}
  >
  ```

- [ ] **Step 4: Conditionally render panels**

  Wrap the `<main>` element (lines 94-150) with a conditional:

  ```tsx
  {layout !== 'aside' && (
    <main className="min-h-0 overflow-auto p-5">
      {/* existing main content */}
    </main>
  )}
  ```

  Wrap the `<aside>` element (lines 152-216) with a conditional:

  ```tsx
  {layout !== 'main' && (
    <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-l lg:border-t-0">
      {/* existing aside content */}
    </aside>
  )}
  ```

  **Important:** Keep all existing content inside `main` and `aside` unchanged. Only add the `{layout !== 'aside' && (` and `{layout !== 'main' && (` wrappers around them.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/pages/tasks/TaskDetail.tsx
  git commit -m "$(cat <<'EOF'
feat: add panel layout state and conditional rendering

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
  )"
  ```

---

### Task 2: Add Collapse/Expand Buttons

**Files:**
- Modify: `frontend/src/pages/tasks/TaskDetail.tsx`

- [ ] **Step 1: Add the output timeline panel button**

  Find the output timeline section header (around lines 96-103):

  ```tsx
  <div className="flex items-center justify-between gap-3">
    <h2 className="text-sm font-semibold text-[var(--text)]">
      {t('pages.tasks.outputTimeline')}
    </h2>
    <span className="text-xs text-[var(--text-secondary)]">
      {t('pages.tasks.latestSeq', { seq: selectedTask.latest_output_seq })}
    </span>
  </div>
  ```

  Replace it with:

  ```tsx
  <div className="flex items-center justify-between gap-3">
    <h2 className="text-sm font-semibold text-[var(--text)]">
      {t('pages.tasks.outputTimeline')}
    </h2>
    <div className="flex items-center gap-3">
      <span className="text-xs text-[var(--text-secondary)]">
        {t('pages.tasks.latestSeq', { seq: selectedTask.latest_output_seq })}
      </span>
      <button
        type="button"
        onClick={() => setLayout(layout === 'main' ? 'split' : 'main')}
        className="rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
        aria-label={layout === 'main' ? 'Collapse panel' : 'Expand panel'}
      >
        {layout === 'main' ? '<<' : '>>'}
      </button>
    </div>
  </div>
  ```

- [ ] **Step 2: Add the summary panel button**

  Find the start of the `<aside>` element (around line 152):

  ```tsx
  <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-l lg:border-t-0">
    <div className="space-y-5">
      <section>
        <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
          {t('pages.tasks.summary')}
        </h2>
  ```

  Replace the opening of the aside with:

  ```tsx
  <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-l lg:border-t-0">
    <div className="mb-2 flex items-center justify-between">
      <h2 className="text-sm font-semibold text-[var(--text)]">
        {t('pages.tasks.summary')}
      </h2>
      <button
        type="button"
        onClick={() => setLayout(layout === 'aside' ? 'split' : 'aside')}
        className="rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
        aria-label={layout === 'aside' ? 'Collapse panel' : 'Expand panel'}
      >
        {layout === 'aside' ? '>>' : '<<'}
      </button>
    </div>
    <div className="space-y-5">
  ```

  Then remove the original `<h2 className="mb-2 text-sm font-semibold text-[var(--text)]">{t('pages.tasks.summary')}</h2>` that was inside the first `<section>` (since it's now moved outside).

  The first section should now start directly with the card container:

  ```tsx
  <section>
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
      <MetadataRow ... />
      ...
    </div>
  </section>
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/pages/tasks/TaskDetail.tsx
  git commit -m "$(cat <<'EOF'
feat: add panel collapse/expand buttons

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
  )"
  ```

---

### Task 3: Type Check and Visual Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run type check**

  ```bash
  cd frontend && node_modules/.bin/tsc -b
  ```

  Expected: No TypeScript errors.

- [ ] **Step 2: Start dev server**

  ```bash
  cd frontend && npm run dev
  ```

  Wait for the "ready" message. Note the port.

- [ ] **Step 3: Verify in browser**

  Navigate to `http://localhost:<port>/tasks` and select a task.

  Test these scenarios:

  1. **Default state**: Both panels visible, `>>` button in output timeline header, `<<` button in summary panel header.
  2. **Expand main**: Click `>>` in output timeline. The sidebar should animate away. The button should change to `<<`. The output timeline should fill the width.
  3. **Restore split**: Click `<<` in output timeline. Both panels should return to the split layout.
  4. **Expand aside**: Click `<<` in summary panel. The main panel should hide. The button should change to `>>`. The summary panel should fill the width.
  5. **Restore from aside**: Click `>>` in summary panel. Both panels should return.
  6. **Cross-recovery**: Expand main (hide sidebar), then click `<<` in summary panel (which is hidden but the button would be visible if rendered... wait, the panel is conditionally rendered, so the button is not visible). Verify that clicking the visible `<<` button in the main panel restores split.

- [ ] **Step 4: Stop dev server**

  Press `Ctrl+C`.

- [ ] **Step 5: Commit verification notes (optional)**

  If any tweaks were needed during verification, commit them. If not, no additional commit needed.

---

## Self-Review

**1. Spec coverage:**
- ✅ `useState` for layout mode → Task 1 Step 2
- ✅ Grid class switching with transition → Task 1 Step 3
- ✅ Conditional rendering of panels → Task 1 Step 4
- ✅ Output timeline `>>` button → Task 2 Step 1
- ✅ Summary panel `<<` button → Task 2 Step 2
- ✅ Button direction reversal → embedded in both button onClick handlers
- ✅ Visual verification → Task 3

**2. Placeholder scan:**
- No TBD/TODO/fill-in-later patterns found.
- All code blocks contain complete, copy-pasteable code.
- All commands include expected output.

**3. Type consistency:**
- `layout` type `'split' | 'main' | 'aside'` is consistent across all steps.
- `setLayout` is used with the same type in both buttons.
