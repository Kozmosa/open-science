# Resources Drag Layout, Kimi Engine, and Skill Toggle Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add draggable card layout to the ResourcesPage, introduce a Kimi Claude Code execution engine variant, and replace the binary skill toggle with a ternary mode selector plus batch controls.

**Architecture:** Three independent frontend features sharing the same React + TanStack Query stack. The Kimi engine requires a small backend change to accept a new engine identifier and write a different settings.json template. Skill modes introduce a new `skillModes` field on `ResearchAgentProfileSettings` with backward-compatible migration logic.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, @dnd-kit (drag-and-drop), TanStack Query, FastAPI (backend), Pydantic, pytest.

---

## Feature 1: Draggable Resource Monitoring Cards

### Overview

ResourcesPage cards become draggable within their environment group. Default layout is a two-column grid: left = `SystemResourceCard`, right = `AinrfProcessCard`. Layout state is persisted to localStorage per environment.

### Files

- **Modify:** `frontend/src/pages/ResourcesPage.tsx`
- **Create:** `frontend/src/components/resources/DraggableResourceCard.tsx`
- **Create:** `frontend/src/hooks/useCardLayout.ts`
- **Modify:** `frontend/src/components/resources/index.ts` (export new component)

### Data Model

```typescript
// useCardLayout.ts
export type CardKind = 'system' | 'processes';

export interface CardLayout {
  cardOrder: CardKind[];
}

const defaultLayout: CardLayout = {
  cardOrder: ['system', 'processes'],
};

const storageKey = 'scholar-agent:resources-layout';
```

### Component Design

**`DraggableResourceCard`**
- Wraps either `SystemResourceCard` or `AinrfProcessCard`
- Uses `@dnd-kit/core` `useDraggable` + `useDroppable`
- Drag handle: 6-dot grip icon in the card header (right side)
- Card body is the drop target
- Visual feedback during drag: opacity 50% + slight scale

**`useCardLayout`**
- On mount: read `cardOrder` from localStorage, fallback to `defaultLayout`
- On order change: write to localStorage
- Returns `[layout, setLayout, swapCards]`

**`ResourcesPage`**
- Wraps card container with `<DndContext onDragEnd={handleDragEnd}>`
- Maps `cardOrder` to render cards in that sequence
- CSS Grid: `grid-cols-1 lg:grid-cols-2` (responsive)
- Below `lg` breakpoint: cards stack vertically, drag reorders within stack

### Data Flow

1. Page mounts → `useCardLayout` reads order from localStorage
2. User drags card A over card B → `@dnd-kit` fires `onDragEnd`
3. `handleDragEnd` computes new order, calls `setLayout`
4. `setLayout` writes to localStorage and triggers re-render
5. Cards re-render in new order

### Error Handling

- Corrupted localStorage layout JSON → fallback to `defaultLayout`
- `@dnd-kit` sensors: use `PointerSensor` with `activationConstraint.distance: 8` to prevent accidental drags on touch devices

---

## Feature 2: Kimi Claude Code Execution Engine

### Overview

Add `kimi-claude-code` as a second supported execution engine. The engine uses the same runner infrastructure as `claude-code` but writes a different `settings.json` template pointing to the Kimi API endpoint.

### Files

- **Modify:** `src/ainrf/task_harness/service.py` (engine whitelist)
- **Modify:** `src/ainrf/task_harness/artifacts.py` (Kimi settings template)
- **Modify:** `frontend/src/settings/types.ts` (`ExecutionEngineId`)
- **Modify:** `frontend/src/settings/defaults.ts` (default Kimi profile)
- **Modify:** `frontend/src/settings/storage.ts` (engine id normalization)
- **Modify:** `frontend/src/pages/SettingsPage.tsx` (select options)

### Backend Changes

**`task_harness/service.py`**

Current code (line 200-202):
```python
resolved_execution_engine = execution_engine or _EXECUTION_ENGINE
if resolved_execution_engine != _EXECUTION_ENGINE:
    raise TaskHarnessError(f"Unsupported execution engine: {resolved_execution_engine}")
```

Change to whitelist:
```python
_SUPPORTED_ENGINES = {"claude-code", "kimi-claude-code"}
resolved_execution_engine = execution_engine or _EXECUTION_ENGINE
if resolved_execution_engine not in _SUPPORTED_ENGINES:
    raise TaskHarnessError(f"Unsupported execution engine: {resolved_execution_engine}")
```

**`task_harness/artifacts.py`**

Add `KIMI_SETTINGS_TEMPLATE` constant and modify `write_claude_settings_artifact` (or add a new dispatcher function) to write the correct template based on engine:

```python
KIMI_SETTINGS_TEMPLATE = {
    "env": {
        "ANTHROPIC_AUTH_TOKEN": "sk-xxxx",
        "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding/",
        "ENABLE_TOOL_SEARCH": "false",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-for-coding",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-for-coding",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "kimi-for-coding",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000"
    },
    "model": "kimi-for-coding",
    "skipDangerousModePermissionPrompt": True
}
```

`write_claude_settings_artifact` receives `execution_engine: str` and selects template accordingly.

### Frontend Changes

**`settings/types.ts`**

```typescript
export type ExecutionEngineId = 'claude-code' | 'kimi-claude-code';
```

**`settings/defaults.ts`**

Add:
```typescript
export function createKimiResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: 'kimi-claude-code-default',
    label: 'Kimi Claude Code Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: JSON.stringify({
      env: {
        ANTHROPIC_AUTH_TOKEN: 'sk-xxxx',
        ANTHROPIC_BASE_URL: 'https://api.kimi.com/coding/',
        ENABLE_TOOL_SEARCH: 'false',
        ANTHROPIC_DEFAULT_HAIKU_MODEL: 'kimi-for-coding',
        ANTHROPIC_DEFAULT_SONNET_MODEL: 'kimi-for-coding',
        ANTHROPIC_DEFAULT_OPUS_MODEL: 'kimi-for-coding',
        CLAUDE_CODE_AUTO_COMPACT_WINDOW: '400000'
      },
      model: 'kimi-for-coding',
      skipDangerousModePermissionPrompt: true
    }, null, 2),
  };
}
```

Update `createDefaultTaskConfigurationSettings()`:
```typescript
researchAgentProfiles: [
  createDefaultResearchAgentProfile(),
  createKimiResearchAgentProfile(),
],
```

**`SettingsPage.tsx`**

Execution engine select 从 disabled + single option 改为正常选择：
```tsx
<Select value={taskConfiguration.defaultExecutionEngineId} onChange={...}>
  <option value="claude-code">Claude Code</option>
  <option value="kimi-claude-code">Kimi Claude Code</option>
</Select>
```

### Data Flow

1. User selects engine in SettingsPage → saved to `WebUiSettingsDocument.taskConfiguration.defaultExecutionEngineId`
2. User creates task → frontend sends `execution_engine` in payload
3. Backend validates against `_SUPPORTED_ENGINES` whitelist
4. `write_claude_settings_artifact` selects correct template based on engine
5. Task runs with Kimi API endpoint

### Error Handling

- Invalid engine id from frontend → `400 Bad Request` with clear message
- Kimi template JSON parse error → caught at template generation time, fallback to empty dict

---

## Feature 3: Skill Ternary Mode Toggle + Batch Controls

### Overview

Replace the binary skill toggle in TaskConfigurationSection with a ternary mode selector (`disabled` / `enabled` / `auto`). Add batch buttons to set all skills to the same mode at once.

### Files

- **Modify:** `frontend/src/settings/types.ts`
- **Modify:** `frontend/src/settings/defaults.ts`
- **Modify:** `frontend/src/settings/storage.ts`
- **Modify:** `frontend/src/components/ui/SkillToggleGroup.tsx`
- **Modify:** `frontend/src/pages/SettingsPage.tsx`

### Data Model

**`settings/types.ts`**

```typescript
export type SkillMode = 'disabled' | 'enabled' | 'auto';

export interface ResearchAgentProfileSettings {
  profileId: string;
  label: string;
  systemPrompt: string;
  skills: string[];
  skillModes: Record<string, SkillMode>;
  skillsPrompt: string;
  settingsJson: string;
}
```

### Backward Compatibility (storage.ts)

In `normalizeTaskConfigurationSettings`, when normalizing each `ResearchAgentProfileSettings`:

```typescript
let skillModes: Record<string, SkillMode> = {};
if (isRecord(item.skillModes)) {
  for (const [skillId, mode] of Object.entries(item.skillModes)) {
    if (mode === 'disabled' || mode === 'enabled' || mode === 'auto') {
      skillModes[skillId] = mode;
    }
  }
} else {
  // Migrate from old skills[] array
  hadFallback = true;
  for (const skillId of skills) {
    skillModes[skillId] = 'enabled';
  }
}
```

When saving, `skills` is derived from `skillModes`:
```typescript
skills: Object.entries(skillModes)
  .filter(([, mode]) => mode === 'enabled')
  .map(([skillId]) => skillId),
```

### UI Design

**`SkillToggleGroup`**

Each button cycles through three states on click:
- `disabled` → `enabled` → `auto` → `disabled`

Visual styles:
- `disabled`: `bg-gray-100 text-gray-400` (低对比度，暗示不可用)
- `enabled`: `bg-[var(--apple-blue)] text-white` (蓝色，当前选中态)
- `auto`: `bg-emerald-100 text-emerald-800` (绿色，带 "AUTO" 角标)

Button layout: `flex flex-wrap gap-2` (同现有)

**Batch controls** (放在 `SkillToggleGroup` 上方)

```tsx
<div className="flex gap-2 mb-2">
  <Button variant="secondary" size="sm" onClick={enableAll}>Enable All</Button>
  <Button variant="secondary" size="sm" onClick={disableAll}>Disable All</Button>
  <Button variant="secondary" size="sm" onClick={autoAll}>Auto All</Button>
</div>
```

Each batch button iterates all `availableSkills` and sets their mode uniformly.

### Data Flow

1. `TaskConfigurationSection` holds `profileDraft.skillModes: Record<string, SkillMode>`
2. `SkillToggleGroup` receives `skillModes` + `availableSkills`, renders buttons with current mode
3. Click on skill button → cycle mode → `onChange(newSkillModes)` → `setProfileDraft`
4. Click batch button → set all skills to same mode → `onChange(newSkillModes)`
5. Save → `onSaveResearchAgentProfile(profileDraft)` → writes to localStorage with both `skillModes` and derived `skills`

### Error Handling

- Unknown mode value in loaded data → treated as `'disabled'` during normalization
- `availableSkills` empty → `SkillToggleGroup` renders empty, batch buttons disabled

---

## Testing Strategy

### Frontend

- **`ResourcesPage.test.tsx`**: Verify default two-column layout renders. Simulate drag via `@dnd-kit` test utilities. Verify localStorage write after reorder.
- **`SettingsPage.test.tsx`**: Verify Kimi engine appears in select. Verify skill button cycles through three modes. Verify batch buttons set all skills uniformly.
- **`settings/storage.test.ts`**: Verify old v3 data (without `skillModes`) loads correctly with migration. Verify saved data includes `skillModes`.

### Backend

- **`tests/test_api_tasks.py`**: Send `execution_engine: 'kimi-claude-code'` in task creation payload. Verify task is accepted and `claude-settings.json` contains Kimi template fields (`ANTHROPIC_BASE_URL` pointing to Kimi endpoint).
- **`tests/test_task_harness_service.py`** (if exists): Verify unsupported engine returns 400.

---

## Cross-Cutting Concerns

### localStorage Version

`WebUiSettingsDocument.version` stays at `3`. The `skillModes` addition is handled within v3 normalization as a backward-compatible field (absence = migrate from `skills`). No version bump needed.

### i18n

New UI strings to add to `frontend/src/i18n/messages.ts`:
- `pages.settings.taskConfiguration.enableAll`
- `pages.settings.taskConfiguration.disableAll`
- `pages.settings.taskConfiguration.autoAll`
- `pages.settings.taskConfiguration.executionEngineKimi`

### Dependencies

New npm dependency: `@dnd-kit/core` and `@dnd-kit/sortable` (or `@dnd-kit/utilities`).

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```
