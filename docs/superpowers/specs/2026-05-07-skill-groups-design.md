# Skill Groups Toggle Design

> **Goal:** Add optional `package` field to skills and group them in the UI by package, with group-level toggle and expand/collapse controls.

**Architecture:** Backend adds optional `package` field to skill schemas; ARIS skills auto-populate with `"aris"`. Frontend `SkillToggleGroup` groups skills by package, shows group-level aggregate state, and allows batch toggling. Skills without `package` fall into an "未分组" bucket.

**Tech Stack:** Python/FastAPI backend, React/TypeScript frontend, existing `SkillToggleGroup` pill component.

---

## Data Model Changes

### Backend Schemas (`src/ainrf/api/schemas.py`)

Add `package` to `SkillItem` and `SkillDetail`:

```python
class SkillItem(BaseModel):
    skill_id: str
    label: str
    description: str | None = None
    inject_mode: Literal["auto", "prompt_only", "disabled"]
    dependencies: list[str] = []
    package: str | None = None  # NEW

class SkillDetail(BaseModel):
    skill_id: str
    label: str
    description: str | None = None
    version: str
    author: str
    dependencies: list[str] = []
    inject_mode: Literal["auto", "prompt_only", "disabled"]
    settings_fragment: dict[str, Any]
    mcp_servers: list[str] = []
    hooks: list[str] = []
    allowed_agents: list[str] = []
    skill_md: str | None = None
    package: str | None = None  # NEW
```

### Frontend Types (`frontend/src/types/index.ts`)

```ts
export interface SkillItem {
  skill_id: string;
  label: string;
  description: string | null;
  inject_mode: 'auto' | 'prompt_only' | 'disabled';
  dependencies: string[];
  package?: string;  // NEW
}

export interface SkillDetail {
  skill_id: string;
  label: string;
  description: string | null;
  version: string;
  author: string;
  dependencies: string[];
  inject_mode: 'auto' | 'prompt_only' | 'disabled';
  settings_fragment: Record<string, unknown>;
  mcp_servers: string[];
  hooks: string[];
  allowed_agents: string[];
  skill_md: string | null;
  package?: string;  // NEW
}
```

### ARIS Skill JSON Generation

Modify the code that auto-generates `skill.json` for ARIS skills to inject `"package": "aris"`.

Location: the ARIS skill discovery/packaging code (to be identified during implementation — likely in `src/ainrf/skills/` or similar).

**Rule:** If a skill already has `package` set in its metadata, preserve it. Otherwise default to `"aris"` for skills sourced from the ARIS package.

---

## Component Design

### SkillToggleGroup Refactor (`frontend/src/components/ui/SkillToggleGroup.tsx`)

Props remain unchanged:

```ts
interface SkillToggleGroupProps {
  skills: SkillItem[];
  skillModes: Record<string, SkillMode>;
  onChange: (skillModes: Record<string, SkillMode>) => void;
}
```

Internal behavior:

1. **Group skills** by `skill.package ?? '__ungrouped__'`
2. Sort groups alphabetically, with "未分组" always last
3. Render a `SkillGroupHeader` + collapsible content per group

### SkillGroupHeader (new inline component)

Layout per group:

```
┌─────────────────────────────────────────┐
│ [Toggle]  Group Name          [▼]       │  ← header row
├─────────────────────────────────────────┤
│ [skill A] [skill B] [skill C]           │  ← expanded content
└─────────────────────────────────────────┘
```

**Toggle button (left side):**
- Shows aggregate state of all skills in the group
- All same mode → shows that mode (`enabled` / `auto` / `disabled`)
- Mixed → shows `mixed` state with distinct visual (e.g., striped background or half-filled indicator)
- Clicking cycles ALL skills in the group: `disabled` → `enabled` → `auto` → `disabled`

**Chevron (right side):**
- ▼ when expanded, ▶ when collapsed
- Clicking toggles expand/collapse without touching skill states

**Defaults:**
- "未分组" → expanded by default
- Named groups (`package` set) → collapsed by default

### Individual Skill Pills

Unchanged from current behavior: each pill button cycles its own mode on click. Only visible when group is expanded.

---

## Data Flow

### Group State Derivation (computed, not stored)

```ts
function getGroupMode(
  skillModes: Record<string, SkillMode>,
  skillIds: string[]
): SkillMode | 'mixed' {
  const modes = skillIds.map((id) => skillModes[id] ?? 'disabled');
  if (modes.length === 0) return 'disabled';
  const first = modes[0];
  if (modes.every((m) => m === first)) return first;
  return 'mixed';
}
```

### Group Toggle Action

```ts
function toggleGroup(
  skillModes: Record<string, SkillMode>,
  skillIds: string[],
  nextMode: SkillMode
): Record<string, SkillMode> {
  const updated = { ...skillModes };
  for (const id of skillIds) updated[id] = nextMode;
  return updated;
}
```

### Expand/Collapse State

```ts
const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(
  () => {
    const defaults: Record<string, boolean> = {};
    // ungrouped expanded, named groups collapsed
    return defaults;
  }
);
```

Ephemeral React state — not persisted to localStorage or backend.

### Full Flow

1. Parent (`SettingsPage` or `TaskCreateForm`) fetches skills (now with `package`) from API
2. Parent passes `skills` + `skillModes` → `SkillToggleGroup`
3. `SkillToggleGroup` computes groups internally
4. User clicks **group toggle** → `SkillToggleGroup` computes next mode, calls `onChange` with updated `skillModes`
5. User clicks **individual skill** → same as today, `onChange` with single skill updated
6. Parent re-renders with new `skillModes`, group aggregate state recalculates
7. User clicks **chevron** → only `expandedGroups` state changes, no `onChange` call

---

## Error Handling & Edge Cases

| Case | Behavior |
|------|----------|
| Skill has no `package` | Placed in "未分组" bucket |
| Empty skill list | Render empty state (same as today) |
| All skills in group already same mode | Group toggle advances to next mode normally |
| Group has only one skill | Group toggle behaves identically to clicking that single skill |
| Mixed state + group toggle click | Sets ALL skills in group to `enabled` (first step after mixed) |
| `skillModes` has entry for skill not in `skills` | Ignored for grouping, preserved in output |

---

## Testing Strategy

### Backend Tests

- `test_skill_item_schema_serializes_package` — verify `package` is included in JSON when set, omitted when `None`
- `test_aris_skill_json_has_package` — verify auto-generated ARIS skill.json includes `"package": "aris"`

### Frontend Tests

**`SkillToggleGroup` — Grouping:**
- Skills with same `package` render under shared group header
- Skills without `package` render under "未分组"
- Multiple distinct packages render as multiple group headers

**`SkillToggleGroup` — Group Toggle:**
- Clicking group toggle when all skills are `disabled` sets all to `enabled`
- Clicking group toggle when mixed sets all to `enabled`
- Group header shows correct aggregate state badge

**`SkillToggleGroup` — Expand/Collapse:**
- Chevron click toggles visibility of group skills
- "未分组" defaults expanded
- Named groups default collapsed
- Collapsing does not change any skill mode

**`SkillToggleGroup` — Individual Toggle (regression):**
- Single skill click still cycles its own mode
- Works correctly inside expanded groups

---

## Backward Compatibility

- `package` is **optional** on both backend and frontend
- Skills without `package` continue to work exactly as before, just grouped under "未分组"
- Existing `skillModes` in localStorage / API payloads are unaffected — grouping is purely a UI presentation concern
- No migration needed for stored settings
