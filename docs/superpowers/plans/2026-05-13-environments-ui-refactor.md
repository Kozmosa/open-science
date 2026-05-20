# Environments Page UI Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the Environments page to a single environment list card with inline actions and a modal-based environment editor. Remove the ProjectReferenceEditor card and move "set as default" to a per-row button.

**Architecture:** Single-file restructure of `EnvironmentsPage.tsx`. The page becomes a `PageShell > SectionStack > SectionCard(table)` layout. The EnvironmentEditor moves from an inline collapsible SectionCard into a `<Modal>`. The ProjectReferenceEditor is deleted entirely; its "set default" becomes an action button per environment row.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, vitest + @testing-library/react

**Spec:** `docs/superpowers/specs/2026-05-13-environments-ui-refactor-design.md`

---

### Task 1: Remove PageHeader and restructure outer layout

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`

- [ ] **Step 1: Remove PageHeader import and usage**

Remove the `PageHeader` import from `../components/ui`. Delete the `<PageHeader .../>` JSX block (lines ~741-745).

- [ ] **Step 2: Wrap page in PageShell**

Add `import { PageShell, SectionStack } from '../components/layout'`. Wrap the SectionStack in `<PageShell>`:

```tsx
return (
  <PageShell>
    <SectionStack actions={...}>
      {content}
    </SectionStack>
    {detectionModal}
  </PageShell>
);
```

Remove the outer `<div className="space-y-8">` wrapper.

- [ ] **Step 3: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.tsx
git commit -m "ui: wrap EnvironmentsPage in PageShell, remove PageHeader"
```

---

### Task 2: Move actions into environment list card header

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`

- [ ] **Step 1: Merge action bar into list card header**

Currently the `SectionStack` has an `actions` prop containing the "Current selection" + "Add Environment" SectionCard. Move this content into the environment list SectionCard's header.

Replace:
```tsx
<SectionStack
  actions={
    <SectionCard className="flex flex-wrap items-center justify-between gap-3 p-5">
      <current selection display> <Add button>
    </SectionCard>
  }
>
  <div className="grid ...">
    <SectionCard className="space-y-4">  ← list card
      <SectionHeader title="Environment list" ... />
      <table>...</table>
    </SectionCard>
    <div className="space-y-6">
      <EnvironmentEditor ... />
      <ProjectReferenceEditor ... />
    </div>
  </div>
</SectionStack>
```

To:
```tsx
<SectionStack>
  <SectionCard
    header={
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
            {t('pages.environments.currentSelection')}
          </p>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {activeEnvironmentSummary}
          </p>
        </div>
        <Button onClick={handleCreate}>
          {t('pages.environments.addEnvironment')}
        </Button>
      </div>
    }
  >
    <table>...</table>
  </SectionCard>
</SectionStack>
```

Remove the `actions` prop from SectionStack. Remove the old `SectionHeader title="Environment list"` since the card header now shows current selection + add button.

- [ ] **Step 2: Remove the two-column grid**

Delete the `<div className="grid gap-6 xl:grid-cols-[...]">` wrapper. The page now has a single SectionCard with the table.

- [ ] **Step 3: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.tsx
git commit -m "ui: merge environment actions into list card header"
```

---

### Task 3: Convert EnvironmentEditor to a Modal

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add i18n keys for modal titles**

In `frontend/src/i18n/messages.ts`, add to the `components.environmentEditor` section:

EN (near line 576):
```ts
modalCreateTitle: 'Add Environment',
modalEditTitle: 'Edit Environment',
```

ZH (near line 1217):
```ts
modalCreateTitle: '添加环境',
modalEditTitle: '编辑环境',
```

- [ ] **Step 2: Replace editorExpanded state with isEditorModalOpen**

```tsx
// Remove:
const [editorExpanded, setEditorExpanded] = useState(false);

// Add:
const [isEditorModalOpen, setEditorModalOpen] = useState(false);
```

Update `handleCreate`:
```tsx
const handleCreate = () => {
  setEditorFormKey((value) => value + 1);
  setEditorMode('create');
  setEditorEnvironmentId(null);
  setEditorModalOpen(true);  // was setEditorExpanded(true)
};
```

Update Edit button handler (in table row):
```tsx
onClick={() => {
  setEditorMode('edit');
  setEditorEnvironmentId(environment.id);
  setEditorModalOpen(true);  // was setEditorExpanded(true)
}}
```

- [ ] **Step 3: Wrap EnvironmentEditor in Modal**

Replace the inline `<EnvironmentEditor .../>` usage with a Modal:

```tsx
<Modal
  isOpen={isEditorModalOpen}
  onClose={() => {
    setEditorModalOpen(false);
    setEditorMode('create');
    setEditorEnvironmentId(null);
  }}
  title={
    editorMode === 'create'
      ? t('components.environmentEditor.modalCreateTitle')
      : t('components.environmentEditor.modalEditTitle')
  }
  size="lg"
>
  <EnvironmentEditor
    key={`${editorMode}-${editorEnvironmentId ?? 'new'}-${editorFormKey}`}
    mode={editorMode}
    environment={editorEnvironment}
    activeEnvironment={selectedEnvironment}
    isSaving={saveMutation.isPending}
    onSubmit={async (values) => {
      await saveMutation.mutateAsync(values);
      setEditorModalOpen(false);
    }}
    onCancel={() => {
      setEditorModalOpen(false);
      setEditorFormKey((value) => value + 1);
      setEditorMode('create');
      setEditorEnvironmentId(null);
    }}
  />
</Modal>
```

- [ ] **Step 4: Simplify EnvironmentEditor - remove SectionCard wrapper**

In the `EnvironmentEditor` function, remove the outer `<SectionCard collapsible expanded={expanded} onToggle={onToggle} header={...}>` wrapper. The form becomes a direct child of the Modal body.

Remove `expanded` and `onToggle` from `EnvironmentEditorProps`. Remove `collapsible`, `expanded`, `onToggle`, `header` props from the SectionCard.

The return becomes just:
```tsx
return (
  <>
    {activeEnvironment ? (active banner) : (no-active placeholder)}
    <form className="space-y-5" onSubmit={handleSubmit}>
      {fields...}
      {buttons...}
    </form>
  </>
);
```

- [ ] **Step 5: Add Modal import**

Make sure `Modal` is imported from `'../components/ui'` (it should already be in imports).

- [ ] **Step 6: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.tsx frontend/src/i18n/messages.ts
git commit -m "ui: convert environment editor to modal"
```

---

### Task 4: Remove ProjectReferenceEditor, add per-row Default button

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add i18n keys for default button**

In `frontend/src/i18n/messages.ts`, add to `pages.environments` section:

EN:
```ts
setDefault: 'Default',
isDefault: 'Is default',
```

ZH:
```ts
setDefault: '默认',
isDefault: '已是默认',
```

- [ ] **Step 2: Delete ProjectReferenceEditor**

Remove the entire `ProjectReferenceEditor` function (lines 345-543) and its `ProjectReferenceEditorProps` interface.

Remove the `<ProjectReferenceEditor .../>` JSX from the page render.

Remove the `ProjectReferenceEditor` from the SectionStack children (the right-side column div is already gone from Task 2).

- [ ] **Step 3: Add Default button to each table row**

In the actions column of each table row, add a "Default" button between "Detect" and "Delete":

```tsx
<Button
  variant="secondary"
  size="sm"
  onClick={() => {
    const projectReference = projectReferenceByEnvironmentId[environment.id];
    if (projectReference?.is_default) return;
    saveProjectReferenceMutation.mutate(
      buildProjectReferenceUpdateRequest({}) as ProjectEnvironmentReferenceUpdateRequest
    );
    // Actually: call mutateAsync with is_default: true
  }}
  disabled={
    saveProjectReferenceMutation.isPending ||
    (projectReferenceByEnvironmentId[environment.id]?.is_default === true)
  }
>
  {projectReferenceByEnvironmentId[environment.id]?.is_default
    ? t('pages.environments.isDefault')
    : t('pages.environments.setDefault')}
</Button>
```

Wait - the set-default logic needs the specific mutation. Let me write the correct handler:

```tsx
<Button
  variant="secondary"
  size="sm"
  onClick={() => {
    saveProjectReferenceMutation.mutate({ is_default: true } as ProjectEnvironmentReferenceUpdateRequest);
  }}
  disabled={
    saveProjectReferenceMutation.isPending ||
    removeProjectReferenceMutation.isPending ||
    projectReferenceByEnvironmentId[environment.id]?.is_default === true
  }
>
  {projectReferenceByEnvironmentId[environment.id]?.is_default
    ? t('pages.environments.isDefault')
    : t('pages.environments.setDefault')}
</Button>
```

Actually, looking at the existing mutations, `saveProjectReferenceMutation.mutationFn` expects `ProjectEnvironmentReferenceUpdateRequest`. And `onSetDefault` in the old code called `saveProjectReferenceMutation.mutateAsync({ is_default: true })`. Let me use the same pattern:

```tsx
onClick={async () => {
  try {
    await saveProjectReferenceMutation.mutateAsync({ is_default: true });
  } catch { /* error shown by mutation state */ }
}}
```

- [ ] **Step 4: Remove unused state and queries related to ProjectReferenceEditor**

Keep `saveProjectReferenceMutation`, `removeProjectReferenceMutation`, `projectReferenceByEnvironmentId` — they're still needed for the Default button and the Referenced badge.

Remove any state/code that was ONLY used by the ProjectReferenceEditor (e.g., `onSetDefault`, `onClearDefault`, `onRemove` handler functions, `ProjectRefFormValues` state in the editor).

Keep `saveProjectReferenceMutation` and `removeProjectReferenceMutation` since the Default button and badges still need them.

- [ ] **Step 5: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.tsx frontend/src/i18n/messages.ts
git commit -m "ui: remove ProjectReferenceEditor, add per-row Default button"
```

---

### Task 5: Update tests and final verification

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.test.tsx` (if exists)

- [ ] **Step 1: Find and update EnvironmentsPage tests**

Check if `frontend/src/pages/EnvironmentsPage.test.tsx` exists. If so, read it and update assertions:
- Remove assertions about PageHeader heading role
- Remove assertions about ProjectReferenceEditor
- Add assertions about the Default button in table rows
- Update EnvironmentEditor tests to check for Modal instead of SectionCard

- [ ] **Step 2: Final type check and test run**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

Expected: 20 test files passed, all tests passing.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.test.tsx
git commit -m "test: update environments page tests for UI refactor"
```
