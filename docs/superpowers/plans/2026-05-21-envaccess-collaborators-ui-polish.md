# EnvAccess & Collaborators UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish EnvAccessTab and CollaboratorsTab to match UsersTab quality — CSS variables, i18n, loading/empty/error states, shared components.

**Architecture:** Extract two shared components (`AccessGrantPanel`, `AccessItemRow`), add i18n keys, rewrite both tabs using the new components and patterns from UsersTab.

**Tech Stack:** React, TypeScript, Tailwind CSS v4, i18n (custom hook)

---

### Task 1: Shared Components + i18n

**Files:**
- Create: `frontend/src/components/settings/AccessGrantPanel.tsx`
- Create: `frontend/src/components/settings/AccessItemRow.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Write `AccessItemRow.tsx`**

```tsx
import type { ReactNode } from 'react';

interface AccessItemRowProps {
  label: string;
  sublabel?: string;
  meta?: ReactNode;
  onRemove: () => void;
  removeLabel: string;
  disabled?: boolean;
}

export function AccessItemRow({ label, sublabel, meta, onRemove, removeLabel, disabled }: AccessItemRowProps) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm">
      <div>
        <span className="font-medium text-[var(--text)]">{label}</span>
        {sublabel && <span className="text-[var(--text-secondary)] ml-2">{sublabel}</span>}
      </div>
      <div className="flex items-center gap-3">
        {meta && <span className="text-xs text-[var(--text-secondary)]">{meta}</span>}
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="text-xs text-red-500 hover:text-red-600 disabled:opacity-50"
        >
          {removeLabel}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write `AccessGrantPanel.tsx`**

```tsx
import type { ReactNode } from 'react';
import type { AdminUserResponse } from '../../types';

interface AccessGrantPanelProps {
  users: AdminUserResponse[];
  selectedUserId: string;
  onUserChange: (id: string) => void;
  onGrant: () => void;
  grantLabel: string;
  userPlaceholder: string;
  disabled?: boolean;
  extraField?: ReactNode;
}

export function AccessGrantPanel({
  users, selectedUserId, onUserChange, onGrant, grantLabel, userPlaceholder, disabled, extraField,
}: AccessGrantPanelProps) {
  const activeUsers = users.filter(u => u.status === 'active');

  return (
    <div className="flex flex-wrap gap-2 items-center p-3 rounded-lg bg-[var(--bg)] border border-dashed border-[var(--border)] mt-2">
      <select
        value={selectedUserId}
        onChange={(e) => onUserChange(e.target.value)}
        className="flex-1 min-w-[140px] text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]"
      >
        <option value="">{userPlaceholder}</option>
        {activeUsers.map((u) => (
          <option key={u.id} value={u.id}>{u.username} ({u.display_name})</option>
        ))}
      </select>
      {extraField}
      <button
        type="button"
        onClick={onGrant}
        disabled={disabled || !selectedUserId}
        className="text-xs px-3 py-1.5 bg-[var(--apple-blue)] text-white rounded disabled:opacity-40"
      >
        {grantLabel}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Add i18n keys to `messages.ts`**

Find the existing `pages.settings.tabs` section and add envAccess and collaborators keys in both EN and ZH sections.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/settings/ frontend/src/i18n/messages.ts
git commit -m "feat(settings): add AccessGrantPanel, AccessItemRow components and i18n keys"
```

---

### Task 2: Rewrite EnvAccessTab

**Files:**
- Rewrite: `frontend/src/pages/settings/EnvAccessTab.tsx`

- [ ] **Step 1: Rewrite EnvAccessTab**

Replace the entire file. Key changes:
- Use `AccessItemRow` and `AccessGrantPanel`
- Replace hardcoded colors with CSS variables
- Add loading spinner, empty state, error state
- Use `useT()` for all text
- Use `Select` component for environment selector

- [ ] **Step 2: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npx vitest run
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/settings/EnvAccessTab.tsx
git commit -m "refactor(settings): polish EnvAccessTab — CSS vars, i18n, states"
```

---

### Task 3: Rewrite CollaboratorsTab

**Files:**
- Rewrite: `frontend/src/pages/settings/CollaboratorsTab.tsx`

- [ ] **Step 1: Rewrite CollaboratorsTab**

Same pattern as EnvAccessTab — use shared components, CSS variables, i18n, states.

- [ ] **Step 2: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npx vitest run
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/settings/CollaboratorsTab.tsx
git commit -m "refactor(settings): polish CollaboratorsTab — CSS vars, i18n, states"
```

---

### Task 4: Integration Verification

- [ ] **Step 1: Run full check**

```bash
cd frontend && node_modules/.bin/tsc -b && npx vitest run
```

Expected: 133+ tests pass, type check clean.

- [ ] **Step 2: Commit worklog if needed, push**
