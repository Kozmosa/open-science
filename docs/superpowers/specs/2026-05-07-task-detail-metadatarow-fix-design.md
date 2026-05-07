# Task Detail MetadataRow UI Bug Fix

## Problem

The `MetadataRow` component in `TaskDetail.tsx` has two styling issues in the task detail panel's sidebar cards:

1. **Text overflow**: Long values (e.g., `resolved_workdir`, `snapshot_path`, `command`) exceed the card boundary because the value span has `max-w-[70%]` but no truncation or word-breaking.
2. **Poor alignment**: Labels have variable widths, so values start at different horizontal positions across rows, creating a messy visual.

## Design

### Approach

Use fixed-width labels with flexible, truncated values (Option C from brainstorming).

### Changes

**File**: `frontend/src/pages/tasks/TaskDetail.tsx` — `MetadataRow` component (lines 13-30)

| Before | After |
|--------|-------|
| `justify-between` | `gap-4` |
| Label: no fixed width | Label: `w-28 shrink-0` |
| Value: `max-w-[70%]` | Value: `min-w-0 flex-1 truncate` |

**Result layout**:
```tsx
<div className="flex items-start gap-4 border-b border-[var(--border)] py-2 last:border-0">
  <span className="w-28 shrink-0 text-xs text-[var(--text-secondary)]">{label}</span>
  <span className="min-w-0 flex-1 truncate text-right text-xs font-medium text-[var(--text)]">
    {value ?? fallback}
  </span>
</div>
```

### Behavior

- All labels occupy the same 112px width, so all values begin at the same horizontal position.
- Values fill the remaining card width and truncate with `...` if too long.
- Native browser tooltip on hover shows the full untruncated value.
- No changes to card containers, header, or other sections.

## Scope

- Single file, single component.
- No API, state, or behavior changes.
