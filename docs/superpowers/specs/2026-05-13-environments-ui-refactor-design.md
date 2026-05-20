# Design Spec: Environments Page UI Refactor

## Context

The Environments page has accumulated complexity: a separate PageHeader, action bar
SectionCard, two-column grid with editor cards on the right, and a
ProjectReferenceEditor card. This spec simplifies the page to a single
environment list with inline actions and a modal editor.

## Changes

### 1. Remove PageHeader

The page title "Containers / 容器" is already shown in the top header bar.
Remove the PageHeader component from the page.

### 2. Environment list header absorbs actions + selection

Move the "Add Environment" button and "Current selection" display into the
environment list SectionCard's header, replacing the current "Environment list"
title row.

Layout: `[Current selection info] [Add Environment button]` as a flex row
in the SectionCard header.

### 3. Environment editor becomes a Modal

Replace the inline `<SectionCard collapsible>` EnvironmentEditor with a `<Modal>`.
- Open on "Add Environment" click (create mode) or "Edit" click (edit mode)
- Modal title: "添加环境 / Add Environment" or "编辑环境 / Edit Environment"
- All form fields stay the same
- Save/Cancel buttons stay the same
- Close on save, cancel, or backdrop click

New state: `isEditorModalOpen: boolean` replaces `editorExpanded`.

### 4. Remove ProjectReferenceEditor card

Delete the entire ProjectReferenceEditor component and its SectionCard from the page.
Move the "Set as project default" functionality to a per-row button in the
environment list.

### 5. Add "Default" action button per environment row

Add a "默认 / Default" button to each environment's action buttons (alongside
Use, Edit, Detect, Delete). Behavior:
- If NOT the project default: button sets this environment as the project default
- If already the default: button is disabled with "已是默认 / Is default" text

### 6. Page layout after changes

```
<PageShell>
  <SectionStack>
    <SectionCard>  ← environment list card only
      header: [Current selection + Add button]
      <table>  ← environment list table
        each row: Alias | Host | Auth | Detection | [Use] [Edit] [Default] [Detect] [Delete]
      </table>
    </SectionCard>
  </SectionStack>
</PageShell>

<Modal>  ← environment editor (create/edit)
<Modal>  ← detection details (existing)
```

## Files

| File | Action |
|------|--------|
| `frontend/src/pages/EnvironmentsPage.tsx` | Major restructure |
| `frontend/src/i18n/messages.ts` | Add modal title keys, default button keys |
| `frontend/src/pages/EnvironmentsPage.test.tsx` (if exists) | Update tests |
| `frontend/src/pages/environments/helpers.ts` | May need updates |

## Deleted

- ProjectReferenceEditor component (inline in EnvironmentsPage.tsx)
- EnvironmentEditor's SectionCard wrapper (form fields move to Modal body)

## What Does NOT Change

- Environment list table structure (columns, data)
- Detection modal
- EnvironmentEditor form fields
- API calls (create, update, delete, detect, project reference mutations)
- SectionStack usage (kept but simplified)

## Verification

1. Type check: `cd frontend && node_modules/.bin/tsc -b`
2. Tests: `npm run test:run`
3. Manual: open page → see list with header actions → click Add → modal opens → fill form → save → row appears
4. Manual: click Edit → modal opens with data → edit → save
5. Manual: click Default → environment becomes project default
6. Manual: click Detect → detection modal opens as before
