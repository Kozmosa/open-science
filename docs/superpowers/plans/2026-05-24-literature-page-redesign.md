# LiteraturePage Visual Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle LiteraturePage to match other SplitPane-based pages by removing the wrapper div and unifying component styles.

**Architecture:** Remove the `space-y-6 p-4` wrapper between `PageShell` and `SplitPane` so the two-column layout fills the card. Replace native HTML controls in `SubscriptionSidebar`, `PaperFeed`, and `PaperCard` with project-standard `Button`, `Input`, and `Select` components from `components/ui`. Align sidebar list items with the TaskList style.

**Tech Stack:** React, Tailwind CSS, project `components/ui` (Button, Input, Select), lucide-react icons.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/pages/LiteraturePage.tsx` | Modify | Remove wrapper div; pass SplitPane directly as PageShell child |
| `frontend/src/components/literature/SubscriptionSidebar.tsx` | Modify | Replace native controls with UI components; align sidebar colors |
| `frontend/src/components/literature/PaperFeed.tsx` | Modify | Replace native select/button with UI components; align layout |
| `frontend/src/components/literature/PaperCard.tsx` | Modify | Replace action buttons with UI Button component |

---

### Task 1: Remove wrapper div from LiteraturePage

**Files:**
- Modify: `frontend/src/pages/LiteraturePage.tsx`

- [ ] **Step 1: Remove the wrapper div around SplitPane**

  Delete lines 42-48 (`<div className="space-y-6 p-4">` open tag and its closing tag at line 68). Keep the `SplitPane` and its children as direct children of `PageShell`.

  Also delete the unused `useState` import for `sidebarWidth` state if it's no longer needed — but `useState` is still used for `sidebarWidth`, so keep it.

  The resulting file should look like:

  ```tsx
  return (
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
  );
  ```

- [ ] **Step 2: Verify build**

  Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
  Expected: No errors.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/pages/LiteraturePage.tsx
  git commit -m "fix(LiteraturePage): remove wrapper div so SplitPane fills PageShell"
  ```

---

### Task 2: Align SubscriptionSidebar styles

**Files:**
- Modify: `frontend/src/components/literature/SubscriptionSidebar.tsx`

- [ ] **Step 1: Add UI component imports**

  Replace the import block at the top with:

  ```tsx
  import { useState } from 'react';
  import { useMutation, useQueryClient } from '@tanstack/react-query';
  import { Button, Input, Select } from '../../components/ui';
  import { createLiteratureSubscription, deleteLiteratureSubscription } from '../../api';
  import { useT } from '../../i18n';
  import type { LiteratureSubscription } from '../../types';
  ```

- [ ] **Step 2: Update the header and "New Subscription" button**

  Replace the header section (around lines 59-70):

  ```tsx
  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--sidebar-foreground)]">{t('literature.mySubscriptions')}</h2>
        <Button size="sm" onClick={() => setShowNewForm(!showNewForm)}>
          {t('literature.newSubscription')}
        </Button>
      </div>
  ```

- [ ] **Step 3: Replace form inputs with UI components**

  In the new subscription form (lines 73-141), replace the label+input pairs with `FormField`-wrapped `Input` and `Select` components:

  ```tsx
  {showNewForm && (
    <div className="mb-4 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--sidebar-primary)]/50 p-3 text-xs">
      <div>
        <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
          {t('literature.label')}
        </label>
        <Input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t('literature.label')}
          className="text-xs py-2"
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
          {t('literature.keywords')}
        </label>
        <Input
          type="text"
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder="machine learning, NLP"
          className="text-xs py-2"
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
          {t('literature.categories')}
        </label>
        <div className="flex flex-wrap gap-1">
          {ARXIV_CATEGORIES.map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => toggleCategory(cat)}
              className={`rounded-full px-2 py-0.5 text-[10px] transition ${
                selectedCategories.includes(cat)
                  ? 'bg-[var(--apple-blue)] text-white'
                  : 'border border-[var(--border)] text-[var(--text)] hover:bg-[var(--bg)]'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
          {t('literature.frequency')}
        </label>
        <Select
          value={frequency}
          onChange={(e) => setFrequency(e.target.value as 'daily' | 'weekly')}
          className="text-xs py-2"
        >
          <option value="daily">{t('literature.daily')}</option>
          <option value="weekly">{t('literature.weekly')}</option>
        </Select>
      </div>
      <Button
        size="sm"
        onClick={handleCreate}
        disabled={!label.trim() || createMutation.isPending}
        className="w-full"
      >
        {createMutation.isPending ? t('common.loading') : t('literature.create')}
      </Button>
    </div>
  )}
  ```

  Note: Remove the old `disabled` check and `createMutation.isPending` loading text that was on a separate button element.

- [ ] **Step 4: Update subscription list items to match TaskList style**

  Replace the subscription list rendering (lines 145-196) with a flat list style:

  ```tsx
  <div className="flex-1 space-y-1 overflow-y-auto">
    {subscriptions.length === 0 && (
      <p className="py-4 text-center text-[11px] text-[var(--text-secondary)]">
        {t('literature.noSubscriptions')}
      </p>
    )}
    {subscriptions.map((sub) => (
      <div
        key={sub.subscription_id}
        className="group rounded-lg border border-[var(--border)] bg-[var(--sidebar-primary)]/30 p-3 transition hover:bg-[var(--sidebar-primary)]"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-[var(--sidebar-foreground)]">{sub.label}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {sub.keywords.slice(0, 3).map((kw) => (
                <span
                  key={kw}
                  className="rounded-full bg-[var(--bg)] px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)]"
                >
                  {kw}
                </span>
              ))}
            </div>
            <div className="mt-1 flex flex-wrap gap-1">
              {sub.arxiv_categories.slice(0, 3).map((cat) => (
                <span
                  key={cat}
                  className="rounded-full bg-[var(--apple-blue)]/10 px-1.5 py-0.5 text-[10px] text-[var(--apple-blue)]"
                >
                  {cat}
                </span>
              ))}
            </div>
            <span className="mt-1 inline-block text-[10px] text-[var(--text-tertiary)]">
              {t(`literature.${sub.frequency}`)}
            </span>
          </div>
          <button
            type="button"
            onClick={() => deleteMutation.mutate(sub.subscription_id)}
            className="shrink-0 rounded p-1 text-[var(--text-tertiary)] opacity-0 transition hover:text-red-500 group-hover:opacity-100"
            title={t('literature.delete')}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
            </svg>
          </button>
        </div>
      </div>
    ))}
  </div>
  ```

- [ ] **Step 5: Verify build**

  Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
  Expected: No errors.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/components/literature/SubscriptionSidebar.tsx
  git commit -m "style(SubscriptionSidebar): align with project UI components and sidebar theme"
  ```

---

### Task 3: Align PaperFeed styles

**Files:**
- Modify: `frontend/src/components/literature/PaperFeed.tsx`

- [ ] **Step 1: Add UI component imports and icon**

  Replace the import block:

  ```tsx
  import { useQuery } from '@tanstack/react-query';
  import { useState, useCallback } from 'react';
  import { RefreshCw } from 'lucide-react';
  import { Button, Select } from '../../components/ui';
  import { getLiteraturePapers } from '../../api';
  import { useT } from '../../i18n';
  import type { LiteratureSubscription } from '../../types';
  import PaperCard from './PaperCard';
  ```

- [ ] **Step 2: Replace filter controls with UI components**

  Replace the header/filter section (lines 34-67):

  ```tsx
  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Select
          value={selectedSubscriptionId ?? ''}
          onChange={(e) => setSelectedSubscriptionId(e.target.value || undefined)}
          className="w-auto min-w-[160px] text-xs py-2"
        >
          <option value="">{t('literature.mySubscriptions')}</option>
          {subscriptions.map((sub) => (
            <option key={sub.subscription_id} value={sub.subscription_id}>
              {sub.label}
            </option>
          ))}
        </Select>

        <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            className="rounded border-[var(--border)]"
          />
          {t('literature.unreadOnly')}
        </label>

        <Button variant="secondary" size="sm" onClick={handleRefresh} className="ml-auto">
          <RefreshCw size={14} className="mr-1" />
          {t('literature.refresh')}
        </Button>
      </div>
  ```

- [ ] **Step 3: Update paper list container**

  Keep the list container but remove `space-y-3` (PaperCard already has margin):

  ```tsx
      <div className="flex-1 overflow-y-auto">
        {papersQuery.isLoading && papers.length === 0 && (
          <p className="py-8 text-center text-xs text-[var(--text-tertiary)]">{t('common.loading')}</p>
        )}

        {papers.length === 0 && !papersQuery.isLoading && (
          <p className="py-8 text-center text-xs text-[var(--text-tertiary)]">{t('literature.noPapers')}</p>
        )}

        {papers.map((paper) => (
          <PaperCard
            key={`${paper.paper_id}-${paper.subscription_id}`}
            paper={paper}
            onConvertToTask={onConvertToTask}
            onReadChange={() => papersQuery.refetch()}
          />
        ))}
      </div>
    </div>
  );
  ```

- [ ] **Step 4: Verify build**

  Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
  Expected: No errors.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/components/literature/PaperFeed.tsx
  git commit -m "style(PaperFeed): replace native controls with UI components"
  ```

---

### Task 4: Unify PaperCard action buttons

**Files:**
- Modify: `frontend/src/components/literature/PaperCard.tsx`

- [ ] **Step 1: Add Button import**

  Replace the import block:

  ```tsx
  import { useState } from 'react';
  import { useT } from '../../i18n';
  import { Button } from '../../components/ui';
  import type { LiteraturePaper } from '../../types';
  import { markPaperRead } from '../../api';
  ```

- [ ] **Step 2: Replace action bar buttons**

  Replace the action bar (lines 83-109):

  ```tsx
      <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
        {!paper.is_read && (
          <Button variant="secondary" size="sm" onClick={handleMarkRead}>
            {t('literature.markRead')}
          </Button>
        )}
        <Button variant="secondary" size="sm" as="a" href={`https://arxiv.org/abs/${paper.paper_id}`} target="_blank" rel="noopener noreferrer">
          {t('literature.viewarXiv')}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => onConvertToTask(paper.paper_id, paper.subscription_id, paper.title, paper.abstract)}
          disabled={paper.is_converted_to_task}
          className="ml-auto"
        >
          {t('literature.convertToTask')}
        </Button>
      </div>
  ```

  Note: The `Button` component does not have an `as` prop. Since we need a link that looks like a button, use a wrapper pattern:

  ```tsx
        <a
          href={`https://arxiv.org/abs/${paper.paper_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
        >
          {t('literature.viewarXiv')}
        </a>
  ```

  Actually, since `Button` doesn't support `as`, and adding that prop is out of scope, keep the link as a styled anchor that matches the `Button variant="secondary" size="sm"` visual style.

- [ ] **Step 3: Verify build**

  Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
  Expected: No errors.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/components/literature/PaperCard.tsx
  git commit -m "style(PaperCard): unify action buttons with UI Button component"
  ```

---

## Self-Review Checklist

- [x] **Spec coverage:** All four files from the design doc are covered.
- [x] **Placeholder scan:** No TBD, TODO, or vague requirements.
- [x] **Type consistency:** All component props match the actual `components/ui` API (Button has `variant`, `size`, `disabled`; Input has standard input props; Select has standard select props).
- [x] **No `as` prop on Button:** Acknowledged — the arXiv link uses a styled anchor instead.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-24-literature-page-redesign.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach do you prefer?
