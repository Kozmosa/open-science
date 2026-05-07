# Resources Drag Layout, Kimi Engine, and Skill Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add draggable card layout to ResourcesPage, introduce a Kimi Claude Code execution engine, and replace the binary skill toggle with a ternary mode selector plus batch controls.

**Architecture:** Three independent features. Feature 1 is pure frontend UI. Feature 2 is a small backend change (engine whitelist + settings template) plus frontend select. Feature 3 is a frontend data model evolution (`skillModes`) with backward-compatible localStorage migration.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, @dnd-kit, TanStack Query, FastAPI, Pydantic, pytest, vitest.

---

## File Structure

### Feature 1: Draggable Resource Cards

- **Create:** `frontend/src/hooks/useCardLayout.ts` — localStorage-backed card order state
- **Create:** `frontend/src/components/resources/DraggableResourceCard.tsx` — dnd-kit wrapper around SystemResourceCard / AinrfProcessCard
- **Modify:** `frontend/src/components/resources/index.ts` — export DraggableResourceCard
- **Modify:** `frontend/src/pages/ResourcesPage.tsx` — wire up DndContext + useCardLayout
- **Test:** `frontend/src/pages/ResourcesPage.test.tsx` — drag interaction and localStorage persistence

### Feature 2: Kimi Claude Code Engine

- **Modify:** `src/ainrf/task_harness/service.py` — accept `kimi-claude-code` in engine whitelist
- **Modify:** `src/ainrf/task_harness/artifacts.py` — write Kimi template when engine is `kimi-claude-code`
- **Modify:** `frontend/src/settings/types.ts` — extend `ExecutionEngineId`
- **Modify:** `frontend/src/settings/defaults.ts` — add `createKimiResearchAgentProfile()`
- **Modify:** `frontend/src/settings/storage.ts` — handle `kimi-claude-code` in engine normalization (no-op, just ensure it passes through)
- **Modify:** `frontend/src/pages/SettingsPage.tsx` — enable engine select with two options
- **Test:** `tests/test_api_tasks.py` — verify `kimi-claude-code` task creation succeeds

### Feature 3: Skill Ternary Toggle + Batch Controls

- **Modify:** `frontend/src/settings/types.ts` — add `SkillMode` type and `skillModes` field
- **Modify:** `frontend/src/settings/defaults.ts` — add `skillModes: {}` to default profile
- **Modify:** `frontend/src/settings/storage.ts` — normalize/migrate `skillModes` from old `skills[]`
- **Modify:** `frontend/src/components/ui/SkillToggleGroup.tsx` — ternary cycle buttons + batch controls
- **Modify:** `frontend/src/pages/SettingsPage.tsx` — pass `skillModes` instead of `selected` string array
- **Test:** `frontend/src/settings/storage.test.ts` — v3 migration with and without `skillModes`

---

## Task 1: Install @dnd-kit dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install packages**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

Expected: packages installed, `package-lock.json` updated.

- [ ] **Step 2: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "deps: add @dnd-kit for draggable resource cards"
```

---

## Task 2: Create `useCardLayout` hook

**Files:**
- Create: `frontend/src/hooks/useCardLayout.ts`
- Test: `frontend/src/hooks/useCardLayout.test.ts`

- [ ] **Step 1: Write the hook**

```typescript
// frontend/src/hooks/useCardLayout.ts
import { useState, useCallback, useEffect } from 'react';

export type CardKind = 'system' | 'processes';

export interface CardLayout {
  cardOrder: CardKind[];
}

const defaultLayout: CardLayout = {
  cardOrder: ['system', 'processes'],
};

const storageKey = 'scholar-agent:resources-layout';

function readLayout(): CardLayout {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        Array.isArray((parsed as CardLayout).cardOrder) &&
        (parsed as CardLayout).cardOrder.every(
          (k): k is CardKind => k === 'system' || k === 'processes'
        )
      ) {
        return parsed as CardLayout;
      }
    }
  } catch {
    // ignore corrupted storage
  }
  return defaultLayout;
}

function writeLayout(layout: CardLayout): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(layout));
  } catch {
    // ignore storage failures
  }
}

export function useCardLayout() {
  const [layout, setLayoutState] = useState<CardLayout>(readLayout);

  const setLayout = useCallback((layout: CardLayout) => {
    setLayoutState(layout);
    writeLayout(layout);
  }, []);

  const swapCards = useCallback(
    (activeId: CardKind, overId: CardKind) => {
      const order = [...layout.cardOrder];
      const activeIndex = order.indexOf(activeId);
      const overIndex = order.indexOf(overId);
      if (activeIndex === -1 || overIndex === -1) return;
      const [removed] = order.splice(activeIndex, 1);
      order.splice(overIndex, 0, removed);
      setLayout({ cardOrder: order });
    },
    [layout, setLayout]
  );

  return { layout, setLayout, swapCards };
}
```

- [ ] **Step 2: Write the test**

```typescript
// frontend/src/hooks/useCardLayout.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCardLayout } from './useCardLayout';

describe('useCardLayout', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns default layout on first mount', () => {
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['system', 'processes']);
  });

  it('swaps cards and persists to localStorage', () => {
    const { result } = renderHook(() => useCardLayout());
    act(() => {
      result.current.swapCards('system', 'processes');
    });
    expect(result.current.layout.cardOrder).toEqual(['processes', 'system']);
    const stored = window.localStorage.getItem('scholar-agent:resources-layout');
    expect(JSON.parse(stored!).cardOrder).toEqual(['processes', 'system']);
  });

  it('falls back to default when localStorage is corrupted', () => {
    window.localStorage.setItem('scholar-agent:resources-layout', 'not-json');
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['system', 'processes']);
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm run test:run -- src/hooks/useCardLayout.test.ts
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/useCardLayout.ts frontend/src/hooks/useCardLayout.test.ts
git commit -m "feat: add useCardLayout hook for draggable resource cards"
```

---

## Task 3: Create `DraggableResourceCard` component

**Files:**
- Create: `frontend/src/components/resources/DraggableResourceCard.tsx`
- Modify: `frontend/src/components/resources/index.ts`

- [ ] **Step 1: Write the component**

```typescript
// frontend/src/components/resources/DraggableResourceCard.tsx
import { useDraggable, useDroppable } from '@dnd-kit/core';
import type { CardKind } from '../../hooks/useCardLayout';

interface Props {
  kind: CardKind;
  children: React.ReactNode;
}

export default function DraggableResourceCard({ kind, children }: Props) {
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } = useDraggable({
    id: kind,
  });
  const { setNodeRef: setDropRef } = useDroppable({
    id: kind,
  });

  const style: React.CSSProperties = {
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    opacity: isDragging ? 0.5 : 1,
    transition: 'opacity 150ms ease',
  };

  return (
    <div ref={setDropRef} style={style} className="relative">
      <div
        ref={setDragRef}
        {...listeners}
        {...attributes}
        className="absolute right-3 top-3 cursor-grab active:cursor-grabbing"
        title="Drag to reorder"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" className="text-[var(--text-tertiary)]">
          <circle cx="4" cy="4" r="1.5" />
          <circle cx="8" cy="4" r="1.5" />
          <circle cx="12" cy="4" r="1.5" />
          <circle cx="4" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="12" cy="8" r="1.5" />
          <circle cx="4" cy="12" r="1.5" />
          <circle cx="8" cy="12" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
        </svg>
      </div>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Export from index.ts**

```typescript
// frontend/src/components/resources/index.ts
export { default as GpuBar } from './GpuBar';
export { default as CpuRing } from './CpuRing';
export { default as MemoryBar } from './MemoryBar';
export { default as SystemResourceCard } from './SystemResourceCard';
export { default as AinrfProcessCard } from './AinrfProcessCard';
export { default as DraggableResourceCard } from './DraggableResourceCard';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/resources/
git commit -m "feat: add DraggableResourceCard wrapper with dnd-kit"
```

---

## Task 4: Wire up drag-and-drop in ResourcesPage

**Files:**
- Modify: `frontend/src/pages/ResourcesPage.tsx`
- Test: `frontend/src/pages/ResourcesPage.test.tsx`

- [ ] **Step 1: Rewrite ResourcesPage with DndContext**

```tsx
// frontend/src/pages/ResourcesPage.tsx
import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useQuery } from '@tanstack/react-query';
import { getResources } from '../api';
import { SystemResourceCard, AinrfProcessCard, DraggableResourceCard } from '../components/resources';
import { useT } from '../i18n';
import { useCardLayout } from '../hooks/useCardLayout';
import type { CardKind } from '../hooks/useCardLayout';

const cardRenderers: Record<CardKind, (snapshot: any) => React.ReactNode> = {
  system: (snapshot) => <SystemResourceCard snapshot={snapshot} />,
  processes: (snapshot) => (
    <AinrfProcessCard processes={snapshot.ainrf_processes} environment_name={snapshot.environment_name} />
  ),
};

export default function ResourcesPage() {
  const t = useT();
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: getResources,
    refetchInterval: 5000,
    staleTime: 4000,
  });
  const { layout, swapCards } = useCardLayout();

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

  const snapshots = resourcesQuery.data?.items ?? [];

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
          {t('pages.resources.eyebrow')}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{t('pages.resources.title')}</h1>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          {t('pages.resources.description')}
        </p>
      </div>

      {resourcesQuery.isLoading && snapshots.length === 0 && (
        <p className="text-sm text-[var(--text-tertiary)]">{t('pages.resources.loading')}</p>
      )}

      {snapshots.length === 0 && !resourcesQuery.isLoading && (
        <p className="text-sm text-[var(--text-tertiary)]">{t('pages.resources.noData')}</p>
      )}

      <DndContext sensors={sensors} onDragEnd={(event) => {
        const { active, over } = event;
        if (over && active.id !== over.id) {
          swapCards(active.id as CardKind, over.id as CardKind);
        }
      }}>
        {snapshots.map((snapshot) => (
          <div key={snapshot.environment_id} className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {layout.cardOrder.map((kind) => (
              <DraggableResourceCard key={kind} kind={kind}>
                {cardRenderers[kind](snapshot)}
              </DraggableResourceCard>
            ))}
          </div>
        ))}
      </DndContext>
    </div>
  );
}
```

- [ ] **Step 2: Write the test**

```tsx
// frontend/src/pages/ResourcesPage.test.tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ResourcesPage from './ResourcesPage';

vi.mock('../api', () => ({
  getResources: vi.fn(() =>
    Promise.resolve({
      items: [
        {
          environment_id: 'env-1',
          environment_name: 'Localhost',
          timestamp: new Date().toISOString(),
          status: 'ok',
          gpus: [],
          cpu: { percent: 10, core_count: 8 },
          memory: { used_mb: 4000, total_mb: 16000, percent: 25 },
          ainrf_processes: [],
        },
      ],
    })
  ),
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe('ResourcesPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders default two-column layout', async () => {
    render(<ResourcesPage />, { wrapper: Wrapper });
    expect(await screen.findByText('Localhost')).toBeInTheDocument();
    // Both cards rendered
    expect(screen.getByText(/CPU/i)).toBeInTheDocument();
    expect(screen.getByText(/Processes/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend && npm run test:run -- src/pages/ResourcesPage.test.tsx
```

Expected: tests pass.

- [ ] **Step 4: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ResourcesPage.tsx frontend/src/pages/ResourcesPage.test.tsx
git commit -m "feat: wire up draggable resource cards on ResourcesPage"
```

---

## Task 5: Backend — accept `kimi-claude-code` engine

**Files:**
- Modify: `src/ainrf/task_harness/service.py`
- Modify: `src/ainrf/task_harness/artifacts.py`
- Test: `tests/test_api_tasks.py`

- [ ] **Step 1: Update engine whitelist in service.py**

```python
# src/ainrf/task_harness/service.py
# Around line 200, change:
_SUPPORTED_ENGINES = {"claude-code", "kimi-claude-code"}
resolved_execution_engine = execution_engine or _EXECUTION_ENGINE
if resolved_execution_engine not in _SUPPORTED_ENGINES:
    raise TaskHarnessError(f"Unsupported execution engine: {resolved_execution_engine}")
```

- [ ] **Step 2: Add Kimi template and dispatcher in artifacts.py**

```python
# src/ainrf/task_harness/artifacts.py
# Add near the top with other constants:
KIMI_SETTINGS_TEMPLATE = {
    "env": {
        "ANTHROPIC_AUTH_TOKEN": "sk-xxxx",
        "ANTHROPIC_BASE_URL": "https://api.kimi.com/coding/",
        "ENABLE_TOOL_SEARCH": "false",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "kimi-for-coding",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "kimi-for-coding",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "kimi-for-coding",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000",
    },
    "model": "kimi-for-coding",
    "skipDangerousModePermissionPrompt": True,
}

# Modify write_claude_settings_artifact (around line 154):
def write_claude_settings_artifact(
    path: Path,
    settings_json: dict[str, object] | None,
    execution_engine: str = DEFAULT_EXECUTION_ENGINE,
) -> str | None:
    if settings_json is None:
        if execution_engine == "kimi-claude-code":
            write_json(path, KIMI_SETTINGS_TEMPLATE)
            return str(path)
        return None
    write_json(path, settings_json)
    return str(path)
```

Then update the call site in `service.py` around line 207:
```python
settings_artifact_path = write_claude_settings_artifact(
    claude_settings_path(task_dir),
    profile_snapshot.settings_json,
    resolved_execution_engine,
)
```

- [ ] **Step 3: Write the backend test**

In `tests/test_api_tasks.py`, find a test that creates a task and add a variant for Kimi engine. Or add a focused test:

```python
# tests/test_api_tasks.py (add a new test function)
@pytest.mark.anyio
async def test_create_task_with_kimi_engine(
    tmp_path: Path,
) -> None:
    app = make_app(tmp_path)
    environment = app.state.environment_service.create_environment(
        alias="local",
        display_name="Local",
        host="localhost",
        default_workdir="/tmp",
        task_harness_profile="test",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/tasks",
            headers=API_HEADERS,
            json={
                "workspace_id": "workspace-default",
                "environment_id": environment.id,
                "task_profile": "claude-code",
                "execution_engine": "kimi-claude-code",
                "task_input": "Run with Kimi.",
            },
        )
        assert response.status_code == 201
        created = response.json()
        assert created["execution_engine"] == "kimi-claude-code"

        # Verify claude-settings.json contains Kimi endpoint
        task_dir = tmp_path / created["task_id"]
        settings_path = task_dir / "claude-settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["env"]["ANTHROPIC_BASE_URL"] == "https://api.kimi.com/coding/"
        assert data["model"] == "kimi-for-coding"
```

- [ ] **Step 4: Run backend tests**

```bash
uv run pytest tests/test_api_tasks.py -v -k kimi
```

Expected: new test passes.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/task_harness/service.py src/ainrf/task_harness/artifacts.py tests/test_api_tasks.py
git commit -m "feat: add kimi-claude-code execution engine backend support"
```

---

## Task 6: Frontend — add Kimi engine type and default profile

**Files:**
- Modify: `frontend/src/settings/types.ts`
- Modify: `frontend/src/settings/defaults.ts`
- Modify: `frontend/src/settings/storage.ts`

- [ ] **Step 1: Extend ExecutionEngineId type**

```typescript
// frontend/src/settings/types.ts
export type ExecutionEngineId = 'claude-code' | 'kimi-claude-code';
```

- [ ] **Step 2: Add Kimi default profile**

```typescript
// frontend/src/settings/defaults.ts
export function createKimiResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: 'kimi-claude-code-default',
    label: 'Kimi Claude Code Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: JSON.stringify(
      {
        env: {
          ANTHROPIC_AUTH_TOKEN: 'sk-xxxx',
          ANTHROPIC_BASE_URL: 'https://api.kimi.com/coding/',
          ENABLE_TOOL_SEARCH: 'false',
          ANTHROPIC_DEFAULT_HAIKU_MODEL: 'kimi-for-coding',
          ANTHROPIC_DEFAULT_SONNET_MODEL: 'kimi-for-coding',
          ANTHROPIC_DEFAULT_OPUS_MODEL: 'kimi-for-coding',
          CLAUDE_CODE_AUTO_COMPACT_WINDOW: '400000',
        },
        model: 'kimi-for-coding',
        skipDangerousModePermissionPrompt: true,
      },
      null,
      2
    ),
  };
}
```

Then update `createDefaultTaskConfigurationSettings()`:
```typescript
export function createDefaultTaskConfigurationSettings(): TaskConfigurationSettings {
  return {
    defaultExecutionEngineId: 'claude-code',
    researchAgentProfiles: [
      createDefaultResearchAgentProfile(),
      createKimiResearchAgentProfile(),
    ],
    taskConfigurations: createDefaultTaskConfigurations(),
    defaultResearchAgentProfileId,
    defaultTaskConfigurationId: rawPromptTaskConfigurationId,
  };
}
```

- [ ] **Step 3: Update storage.ts to pass engine ID through**

In `normalizeTaskConfigurationSettings`, the `defaultExecutionEngineId` is currently hardcoded to `'claude-code'` at line 148. Change it to read from stored data:

```typescript
// frontend/src/settings/storage.ts
// In normalizeTaskConfigurationSettings return block:
defaultExecutionEngineId:
  value.defaultExecutionEngineId === 'kimi-claude-code'
    ? 'kimi-claude-code'
    : 'claude-code',
```

- [ ] **Step 4: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/settings/types.ts frontend/src/settings/defaults.ts frontend/src/settings/storage.ts
git commit -m "feat: add kimi-claude-code frontend type and default profile"
```

---

## Task 7: Frontend — enable engine select in SettingsPage

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Update the execution engine select**

In `TaskConfigurationSection`, find the execution engine `<Select>` (currently disabled with a single option). Change it to:

```tsx
<FormField label={t('pages.settings.taskConfiguration.executionEngineLabel')}>
  <Select
    aria-label={t('pages.settings.taskConfiguration.executionEngineLabel')}
    value={taskConfiguration.defaultExecutionEngineId}
    onChange={(event) =>
      onSaveTaskConfigurationSettings({
        ...taskConfiguration,
        defaultExecutionEngineId: event.target.value as ExecutionEngineId,
      })
    }
  >
    <option value="claude-code">Claude Code</option>
    <option value="kimi-claude-code">Kimi Claude Code</option>
  </Select>
</FormField>
```

- [ ] **Step 2: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: enable execution engine select with claude-code and kimi-claude-code"
```

---

## Task 8: Frontend — add `SkillMode` type and `skillModes` field

**Files:**
- Modify: `frontend/src/settings/types.ts`
- Modify: `frontend/src/settings/defaults.ts`

- [ ] **Step 1: Add SkillMode type**

```typescript
// frontend/src/settings/types.ts
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

- [ ] **Step 2: Add skillModes to default profile**

```typescript
// frontend/src/settings/defaults.ts
export function createDefaultResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: defaultResearchAgentProfileId,
    label: 'Claude Code Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: '...', // keep existing
  };
}
```

Same for `createKimiResearchAgentProfile()` (already has `skillModes: {}` from Task 6).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/settings/types.ts frontend/src/settings/defaults.ts
git commit -m "feat: add SkillMode type and skillModes field to profile settings"
```

---

## Task 9: Frontend — update storage.ts for skillModes normalization

**Files:**
- Modify: `frontend/src/settings/storage.ts`

- [ ] **Step 1: Normalize skillModes in storage.ts**

In `normalizeTaskConfigurationSettings`, when normalizing each profile (around line 91-115), add skillModes handling:

```typescript
// Inside the flatMap callback for researchAgentProfiles
const skillsPrompt = typeof item.skillsPrompt === 'string' ? item.skillsPrompt : '';
let skills: string[] = [];
if (Array.isArray(item.skills)) {
  skills = item.skills.filter((s): s is string => typeof s === 'string');
} else if (skillsPrompt.trim()) {
  skills = skillsPrompt
    .split(/[,\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

// Normalize skillModes
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

// Derive skills from skillModes for backward compatibility
const derivedSkills = Object.entries(skillModes)
  .filter(([, mode]) => mode === 'enabled')
  .map(([skillId]) => skillId);

return [
  {
    profileId: item.profileId,
    label: item.label,
    systemPrompt: typeof item.systemPrompt === 'string' ? item.systemPrompt : '',
    skills: derivedSkills.length > 0 ? derivedSkills : skills,
    skillModes,
    skillsPrompt,
    settingsJson: typeof item.settingsJson === 'string' ? item.settingsJson : '',
  },
];
```

- [ ] **Step 2: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/settings/storage.ts
git commit -m "feat: normalize and migrate skillModes from skills array in storage"
```

---

## Task 10: Frontend — rewrite SkillToggleGroup with ternary toggle

**Files:**
- Modify: `frontend/src/components/ui/SkillToggleGroup.tsx`

- [ ] **Step 1: Rewrite the component**

```tsx
// frontend/src/components/ui/SkillToggleGroup.tsx
import type { SkillItem } from '../../types';
import type { SkillMode } from '../../settings/types';

interface Props {
  skills: SkillItem[];
  skillModes: Record<string, SkillMode>;
  onChange: (skillModes: Record<string, SkillMode>) => void;
}

const nextMode = (mode: SkillMode): SkillMode => {
  if (mode === 'disabled') return 'enabled';
  if (mode === 'enabled') return 'auto';
  return 'disabled';
};

const buttonClass = (mode: SkillMode): string => {
  switch (mode) {
    case 'enabled':
      return 'bg-[var(--apple-blue)] text-white';
    case 'auto':
      return 'bg-emerald-100 text-emerald-800';
    case 'disabled':
    default:
      return 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]';
  }
};

export default function SkillToggleGroup({ skills, skillModes, onChange }: Props) {
  const cycle = (skillId: string) => {
    const current = skillModes[skillId] ?? 'disabled';
    onChange({ ...skillModes, [skillId]: nextMode(current) });
  };

  const setAll = (mode: SkillMode) => {
    const next: Record<string, SkillMode> = {};
    for (const skill of skills) {
      next[skill.skill_id] = mode;
    }
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setAll('enabled')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Enable All
        </button>
        <button
          type="button"
          onClick={() => setAll('disabled')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Disable All
        </button>
        <button
          type="button"
          onClick={() => setAll('auto')}
          disabled={skills.length === 0}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:opacity-40"
        >
          Auto All
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {skills.map((skill) => {
          const mode = skillModes[skill.skill_id] ?? 'disabled';
          return (
            <button
              key={skill.skill_id}
              type="button"
              onClick={() => cycle(skill.skill_id)}
              title={skill.description ?? skill.label}
              className={[
                'inline-flex items-center rounded-full px-3 py-1.5 text-xs font-medium transition',
                buttonClass(mode),
              ].join(' ')}
            >
              {skill.label}
              <span className="ml-1.5 rounded px-1 py-0.5 text-[10px] font-semibold uppercase opacity-80">
                {mode}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/SkillToggleGroup.tsx
git commit -m "feat: ternary skill mode toggle with Enable All / Disable All / Auto All"
```

---

## Task 11: Frontend — wire up skillModes in SettingsPage

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Update TaskConfigurationSection to use skillModes**

In `TaskConfigurationSection`, change the `SkillToggleGroup` call from:
```tsx
<SkillToggleGroup
  skills={availableSkills}
  selected={profileDraft.skills}
  onChange={(skills) => setProfileDraft((current) => ({ ...current, skills }))}
/>
```

To:
```tsx
<SkillToggleGroup
  skills={availableSkills}
  skillModes={profileDraft.skillModes}
  onChange={(skillModes) =>
    setProfileDraft((current) => ({
      ...current,
      skillModes,
      skills: Object.entries(skillModes)
        .filter(([, mode]) => mode === 'enabled')
        .map(([skillId]) => skillId),
    }))
  }
/>
```

- [ ] **Step 2: Type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: wire up skillModes in SettingsPage TaskConfigurationSection"
```

---

## Task 12: Frontend — add storage migration tests

**Files:**
- Modify: `frontend/src/settings/storage.test.ts`

- [ ] **Step 1: Add skillModes migration test**

```typescript
// frontend/src/settings/storage.test.ts
it('migrates v3 settings without skillModes from skills array', () => {
  window.localStorage.setItem(
    settingsStorageKey,
    JSON.stringify({
      version: 3,
      general: {
        defaultRoute: 'tasks',
        terminal: { fontSize: 13 },
        editor: { fontSize: 14, fontFamily: 'monospace' },
      },
      taskConfiguration: {
        defaultExecutionEngineId: 'claude-code',
        researchAgentProfiles: [
          {
            profileId: 'claude-code-default',
            label: 'Claude Code Default',
            systemPrompt: '',
            skills: ['web-search', 'code-analysis'],
            skillsPrompt: '',
            settingsJson: '',
          },
        ],
        taskConfigurations: [
          { configId: 'raw-prompt', label: 'Raw Prompt', mode: 'raw_prompt' },
        ],
        defaultResearchAgentProfileId: 'claude-code-default',
        defaultTaskConfigurationId: 'raw-prompt',
      },
      projectDefaults: {
        default: {
          defaultEnvironmentId: null,
          defaultWorkspaceId: null,
          selection: { lastEnvironmentId: null, lastWorkspaceId: null },
          environmentDefaults: {},
        },
      },
    })
  );

  const result = readStoredSettings();

  expect(result.recoveryReason).toBeNull();
  const profile = result.settings.taskConfiguration.researchAgentProfiles[0]!;
  expect(profile.skillModes).toEqual({
    'web-search': 'enabled',
    'code-analysis': 'enabled',
  });
  expect(profile.skills).toEqual(['web-search', 'code-analysis']);
});

it('preserves skillModes when present in v3 settings', () => {
  window.localStorage.setItem(
    settingsStorageKey,
    JSON.stringify({
      version: 3,
      general: {
        defaultRoute: 'tasks',
        terminal: { fontSize: 13 },
        editor: { fontSize: 14, fontFamily: 'monospace' },
      },
      taskConfiguration: {
        defaultExecutionEngineId: 'kimi-claude-code',
        researchAgentProfiles: [
          {
            profileId: 'claude-code-default',
            label: 'Claude Code Default',
            systemPrompt: '',
            skills: ['web-search'],
            skillModes: { 'web-search': 'auto', 'code-analysis': 'disabled' },
            skillsPrompt: '',
            settingsJson: '',
          },
        ],
        taskConfigurations: [
          { configId: 'raw-prompt', label: 'Raw Prompt', mode: 'raw_prompt' },
        ],
        defaultResearchAgentProfileId: 'claude-code-default',
        defaultTaskConfigurationId: 'raw-prompt',
      },
      projectDefaults: {
        default: {
          defaultEnvironmentId: null,
          defaultWorkspaceId: null,
          selection: { lastEnvironmentId: null, lastWorkspaceId: null },
          environmentDefaults: {},
        },
      },
    })
  );

  const result = readStoredSettings();
  const profile = result.settings.taskConfiguration.researchAgentProfiles[0]!;
  expect(profile.skillModes).toEqual({
    'web-search': 'auto',
    'code-analysis': 'disabled',
  });
  expect(profile.skills).toEqual(['web-search']);
});
```

- [ ] **Step 2: Run tests**

```bash
cd frontend && npm run test:run -- src/settings/storage.test.ts
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/settings/storage.test.ts
git commit -m "test: verify skillModes migration from old skills array"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ Draggable resource cards (Tasks 1-4)
- ✅ Kimi engine backend + frontend (Tasks 5-7)
- ✅ Skill ternary toggle + batch controls (Tasks 8-11)
- ✅ Storage migration tests (Task 12)

**2. Placeholder scan:**
- No "TBD", "TODO", "implement later" found.
- All steps contain actual code, test code, run commands, and expected output.

**3. Type consistency:**
- `SkillMode` type used consistently across `types.ts`, `SkillToggleGroup.tsx`, `storage.ts`
- `ExecutionEngineId` expanded in `types.ts` and used in `storage.ts` and `SettingsPage.tsx`
- `skillModes: Record<string, SkillMode>` field added to `ResearchAgentProfileSettings` and populated in all creation/normalization paths
