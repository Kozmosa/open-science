# Task Detail Panel Collapse/Expand Design

## Problem

The TaskDetail page has a two-column layout (output timeline on the left, summary sidebar on the right). Users want the ability to expand either panel to full width and collapse the other, for better focus when reading long outputs or reviewing metadata.

## Design

### State Management

A single `useState` in `TaskDetail` component:

```tsx
const [layout, setLayout] = useState<'split' | 'main' | 'aside'>('split');
```

- `'split'`: Default two-column layout.
- `'main'`: Main panel (output timeline) occupies full width; sidebar hidden.
- `'aside'`: Sidebar occupies full width; main panel hidden.

### Layout Switching

The grid container switches class names based on `layout`:

| State | Grid Class |
|-------|------------|
| `split` | `lg:grid-cols-[minmax(0,1fr)_320px]` |
| `main` | `lg:grid-cols-[1fr_0fr]` |
| `aside` | `lg:grid-cols-[0fr_1fr]` |

The grid container also has `transition-all duration-300 ease-in-out` for smooth width transitions.

### Conditional Rendering

The hidden panel is completely unmounted (not just visually hidden). The visible panel naturally fills the remaining space via the grid layout.

### Buttons

**Output Timeline Panel Button**
- Location: Top-right of the output timeline section header (beside the "latest seq" text).
- Label: `>>` when `layout !== 'main'`, `<<` when `layout === 'main'`.
- Action:
  - If `layout === 'split'` → set `layout = 'main'`.
  - If `layout === 'main'` → set `layout = 'split'`.
  - If `layout === 'aside'` → set `layout = 'split'`.

**Summary Panel Button**
- Location: Top-left of the aside sidebar, aligned with the section headers.
- Label: `<<` when `layout !== 'aside'`, `>>` when `layout === 'aside'`.
- Action:
  - If `layout === 'split'` → set `layout = 'aside'`.
  - If `layout === 'aside'` → set `layout = 'split'`.
  - If `layout === 'main'` → set `layout = 'split'`.

**Button Style**
- Small rounded button with muted background.
- Hover state slightly brighter.
- Uses plain text `>>` / `<<` characters (no icons).

### Scope

- Single file: `frontend/src/pages/tasks/TaskDetail.tsx`.
- No new dependencies.
- No API or backend changes.
- No persistence (refresh resets to split layout).
