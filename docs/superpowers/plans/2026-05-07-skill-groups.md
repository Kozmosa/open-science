# Skill Groups Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `package` field to skills and group them in the UI by package, with group-level toggle and expand/collapse controls.

**Architecture:** Backend adds `package` to skill schemas and auto-populates it during skill.json generation. Frontend `SkillToggleGroup` groups skills by `package`, renders group headers with aggregate state toggles and chevron expand/collapse. Skills without `package` fall into a default "未分组" bucket.

**Tech Stack:** Python 3.13/FastAPI/Pydantic backend, React 18/TypeScript/Tailwind frontend, Vitest for frontend tests, pytest for backend tests.

---

## File Map

| File | Action | Responsibility |
|------|--------|--------------|
| `src/ainrf/skills/models.py` | Modify | Add `package` to `SkillDefinition` and `SkillItem`; update `from_json` and `to_skill_item` |
| `src/ainrf/skills/discovery.py` | Modify | Pass `package` through `_scan_directory_skills`, `_scan_skills_json`, and `_BUILTIN_SKILLS` |
| `src/ainrf/skills/json_generator.py` | Modify | Add `package` to generated skill.json; default `"aris"` for core skills |
| `src/ainrf/api/schemas.py` | Modify | Add `package: str \| None = None` to `SkillItemResponse` and `SkillDetailResponse` |
| `src/ainrf/api/routes/skills.py` | Modify | Include `package` in `SkillItemResponse` and `SkillDetailResponse` construction |
| `frontend/src/types/index.ts` | Modify | Add `package?: string` to `SkillItem` and `SkillDetail` |
| `frontend/src/components/ui/SkillToggleGroup.tsx` | Modify | Refactor to grouped rendering with headers, toggle, and expand/collapse |
| `frontend/src/components/ui/SkillToggleGroup.test.tsx` | Create | Tests for grouping, group toggle, expand/collapse, individual toggle |
| `tests/skills/test_json_generator.py` | Modify | Add tests for `package` in generated skill.json |
| `tests/api/test_skills.py` | Modify | Verify `package` is present in API responses |
| `tests/skills/test_discovery.py` | Modify | Verify `discover_full` reads `package` from skill.json |

---

### Task 1: Backend Model — Add `package` to `SkillDefinition`

**Files:**
- Modify: `src/ainrf/skills/models.py`
- Test: `tests/skills/test_discovery.py`

- [ ] **Step 1: Write the failing test**

In `tests/skills/test_discovery.py`, add a test that creates a skill.json with `package` and asserts `discover_full()` reads it:

```python
def test_discover_full_reads_package(tmp_path: Path) -> None:
    """discover_full() reads package field from skill.json."""
    root = tmp_path / "skills"
    root.mkdir()

    skill_dir = root / "packaged-skill"
    skill_dir.mkdir()
    skill_data = {
        "skill_id": "packaged-skill",
        "label": "Packaged Skill",
        "inject_mode": "auto",
        "package": "aris",
    }
    (skill_dir / "skill.json").write_text(json.dumps(skill_data))
    (skill_dir / "SKILL.md").write_text("# Packaged Skill\n\nDescription.\n")

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover_full()

    assert len(results) == 1
    assert results[0].skill_id == "packaged-skill"
    assert results[0].package == "aris"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/skills/test_discovery.py::test_discover_full_reads_package -v
```

Expected: FAIL with `AttributeError: 'SkillDefinition' object has no attribute 'package'`

- [ ] **Step 3: Write minimal implementation**

In `src/ainrf/skills/models.py`:

1. Add `package` to `SkillItem`:

```python
@dataclass(slots=True, frozen=True)
class SkillItem:
    skill_id: str
    label: str
    description: str | None = None
    package: str | None = None
```

2. Add `package` to `SkillDefinition`:

```python
@dataclass(slots=True)
class SkillDefinition:
    skill_id: str
    label: str
    description: str | None = None
    version: str = "1.0.0"
    author: str = "ainrf"
    dependencies: list[str] = field(default_factory=list)
    inject_mode: InjectMode = InjectMode.AUTO
    settings_fragment: dict[str, Any] = field(default_factory=dict)
    mcp_servers: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=lambda: ["claude-code"])
    package: str | None = None
```

3. Update `from_json` to read `package`:

```python
    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SkillDefinition:
        inject_mode = InjectMode(data.get("inject_mode", "auto"))
        return cls(
            skill_id=data["skill_id"],
            label=data["label"],
            description=data.get("description"),
            version=data.get("version", "1.0.0"),
            author=data.get("author", "ainrf"),
            dependencies=data.get("dependencies", []),
            inject_mode=inject_mode,
            settings_fragment=data.get("settings_fragment", {}),
            mcp_servers=data.get("mcp_servers", []),
            hooks=data.get("hooks", []),
            allowed_agents=data.get("allowed_agents", ["claude-code"]),
            package=data.get("package"),
        )
```

4. Update `to_skill_item` to pass `package`:

```python
    def to_skill_item(self) -> SkillItem:
        return SkillItem(
            skill_id=self.skill_id,
            label=self.label,
            description=self.description,
            package=self.package,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/skills/test_discovery.py::test_discover_full_reads_package -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/skills/models.py tests/skills/test_discovery.py
git commit -m "feat: add package field to SkillDefinition and SkillItem"
```

---

### Task 2: Backend Discovery — Pass `package` Through Discovery Pipeline

**Files:**
- Modify: `src/ainrf/skills/discovery.py`
- Test: `tests/skills/test_discovery.py`

- [ ] **Step 1: Write the failing test**

In `tests/skills/test_discovery.py`, add a test that verifies `_scan_directory_skills` and `_scan_skills_json` pass through `package`:

```python
def test_discover_reads_package_from_skills_json(tmp_path: Path) -> None:
    """discover() reads package field from skills.json files."""
    root = tmp_path / "skills-root"
    root.mkdir()
    skills_subdir = root / "skills"
    skills_subdir.mkdir()

    skills_json = skills_subdir / "skills.json"
    skills_json.write_text(
        json.dumps([
            {"skill_id": "json-skill", "label": "JSON Skill", "package": "my-pkg"}
        ])
    )

    service = SkillsDiscoveryService(scan_roots=[root])
    results = service.discover()

    by_id = {s.skill_id: s for s in results}
    assert "json-skill" in by_id
    assert by_id["json-skill"].package == "my-pkg"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/skills/test_discovery.py::test_discover_reads_package_from_skills_json -v
```

Expected: FAIL — `SkillItem` created without `package` field

- [ ] **Step 3: Write minimal implementation**

In `src/ainrf/skills/discovery.py`:

1. Update `_BUILTIN_SKILLS` to include `package="aris"`:

```python
_BUILTIN_SKILLS: list[SkillItem] = [
    SkillItem("web-search", "Web Search", "Search the web for information", package="aris"),
    SkillItem("code-analysis", "Code Analysis", "Analyze and understand code", package="aris"),
    SkillItem("citation", "Citation", "Manage citations and references", package="aris"),
    SkillItem("repo-inspection", "Repo Inspection", "Inspect repository structure and history", package="aris"),
    SkillItem("paper-reading", "Paper Reading", "Read and summarize academic papers", package="aris"),
    SkillItem("writing", "Academic Writing", "Write academic content", package="aris"),
]
```

2. Update `_scan_directory_skills` to read and pass `package`:

In the `manifest.is_file()` branch (around line 33-40), read `package`:

```python
                if manifest.is_file():
                    try:
                        data = json.loads(manifest.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            label = data.get("label", label)
                            description = data.get("description")
                            package = data.get("package")
                    except (json.JSONDecodeError, OSError):
                        pass
                skills.append(SkillItem(skill_id, label, description, package=package))
```

And in the `.json` file branch (around line 42-53), do the same:

```python
                try:
                    data = json.loads(entry.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        label = data.get("label", label)
                        description = data.get("description")
                        package = data.get("package")
                except (json.JSONDecodeError, OSError):
                    pass
                skills.append(SkillItem(skill_id, label, description, package=package))
```

3. Update `_scan_skills_json` to read and pass `package`:

```python
                        skills.append(
                            SkillItem(
                                skill_id=item["skill_id"],
                                label=item.get("label", item["skill_id"]),
                                description=item.get("description"),
                                package=item.get("package"),
                            )
                        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/skills/test_discovery.py::test_discover_reads_package_from_skills_json -v
```

Expected: PASS

- [ ] **Step 5: Run full discovery test suite**

```bash
uv run pytest tests/skills/test_discovery.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/skills/discovery.py tests/skills/test_discovery.py
git commit -m "feat: pass package through skill discovery pipeline"
```

---

### Task 3: Backend API Schema — Add `package` to Response Schemas

**Files:**
- Modify: `src/ainrf/api/schemas.py`
- Modify: `src/ainrf/api/routes/skills.py`
- Test: `tests/api/test_skills.py`

- [ ] **Step 1: Write the failing test**

In `tests/api/test_skills.py`, update `test_get_skill_detail_success` to assert `package`:

Find the assertion block after `payload = response.json()` and add:

```python
    assert payload["package"] is None
```

Also add a new test for a skill with `package`:

```python
@pytest.mark.anyio
async def test_get_skill_detail_with_package(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skill_id = "packaged-skill"
    skill_json = {
        "skill_id": skill_id,
        "label": "Packaged Skill",
        "description": "A skill with package",
        "version": "1.0.0",
        "author": "tester",
        "inject_mode": "auto",
        "package": "aris",
    }
    skill_md = "# Packaged Skill\n\nContent.\n"
    _create_skill_dir(skills_root, skill_id, skill_json, skill_md)

    async with make_client(tmp_path, scan_roots=[skills_root]) as client:
        response = await client.get(f"/skills/{skill_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["package"] == "aris"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/api/test_skills.py::test_get_skill_detail_with_package -v
```

Expected: FAIL — `package` key not in response or assertion fails

- [ ] **Step 3: Write minimal implementation**

In `src/ainrf/api/schemas.py`:

1. Add `package` to `SkillItemResponse`:

```python
class SkillItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    description: str | None = None
    inject_mode: str = "auto"
    dependencies: list[str] = Field(default_factory=list)
    package: str | None = None
```

2. Add `package` to `SkillDetailResponse`:

```python
class SkillDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    label: str
    description: str | None = None
    version: str
    author: str
    dependencies: list[str] = Field(default_factory=list)
    inject_mode: str
    settings_fragment: dict[str, Any] = Field(default_factory=dict)
    mcp_servers: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    skill_md: str | None = None
    package: str | None = None
```

3. In `src/ainrf/api/routes/skills.py`, pass `package` in `list_skills`:

```python
    return SkillListResponse(
        items=[
            SkillItemResponse(
                skill_id=s.skill_id,
                label=s.label,
                description=s.description,
                inject_mode=s.inject_mode.value,
                dependencies=list(s.dependencies),
                package=s.package,
            )
            for s in skills
        ]
    )
```

4. And in `get_skill_detail`:

```python
    return SkillDetailResponse(
        skill_id=skill.skill_id,
        label=skill.label,
        description=skill.description,
        version=skill.version,
        author=skill.author,
        dependencies=list(skill.dependencies),
        inject_mode=skill.inject_mode.value,
        settings_fragment=dict(skill.settings_fragment),
        mcp_servers=list(skill.mcp_servers),
        hooks=list(skill.hooks),
        allowed_agents=list(skill.allowed_agents),
        skill_md=skill_md,
        package=skill.package,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/api/test_skills.py::test_get_skill_detail_with_package tests/api/test_skills.py::test_get_skill_detail_success -v
```

Expected: PASS

- [ ] **Step 5: Run full skills API test suite**

```bash
uv run pytest tests/api/test_skills.py -v
```

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/api/schemas.py src/ainrf/api/routes/skills.py tests/api/test_skills.py
git commit -m "feat: expose package field in skill API responses"
```

---

### Task 4: Backend Generator — Auto-Populate `package` for ARIS Skills

**Files:**
- Modify: `src/ainrf/skills/json_generator.py`
- Test: `tests/skills/test_json_generator.py`

- [ ] **Step 1: Write the failing test**

In `tests/skills/test_json_generator.py`, add tests:

```python
    def test_generates_package_for_core_skill(self):
        frontmatter = {"name": "research-lit"}
        result = generate_skill_json("research-lit", frontmatter, is_core=True)
        assert result["package"] == "aris"

    def test_generates_no_package_for_non_core_skill(self):
        frontmatter = {"name": "custom-skill"}
        result = generate_skill_json("custom-skill", frontmatter, is_core=False)
        assert result.get("package") is None

    def test_preserves_explicit_package_from_frontmatter(self):
        frontmatter = {"name": "custom-skill", "package": "my-org"}
        result = generate_skill_json("custom-skill", frontmatter, is_core=True)
        assert result["package"] == "my-org"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/skills/test_json_generator.py::TestGenerateSkillJson::test_generates_package_for_core_skill -v
```

Expected: FAIL — `KeyError: 'package'`

- [ ] **Step 3: Write minimal implementation**

In `src/ainrf/skills/json_generator.py`, update `generate_skill_json`:

```python
def generate_skill_json(
    skill_dir_name: str,
    frontmatter: dict[str, Any],
    is_core: bool = False,
) -> dict[str, Any]:
    skill_id = skill_dir_name
    label = frontmatter.get("name", skill_dir_name)
    description = frontmatter.get("description", "")
    inject_mode = "auto" if is_core else "disabled"
    package = frontmatter.get("package", "aris" if is_core else None)

    result = {
        "skill_id": skill_id,
        "label": label,
        "description": description,
        "version": "0.0.0",
        "author": "ARIS",
        "inject_mode": inject_mode,
        "dependencies": [],
        "settings_fragment": {},
        "mcp_servers": [],
        "hooks": [],
        "allowed_agents": [],
    }
    if package is not None:
        result["package"] = package
    return result
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/skills/test_json_generator.py::TestGenerateSkillJson -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/skills/json_generator.py tests/skills/test_json_generator.py
git commit -m "feat: auto-populate package=aris for core skills in skill.json generation"
```

---

### Task 5: Frontend Types — Add `package` to Skill Interfaces

**Files:**
- Modify: `frontend/src/types/index.ts`
- Test: `cd frontend && node_modules/.bin/tsc -b` (type-check)

- [ ] **Step 1: Write the type change**

In `frontend/src/types/index.ts`, add `package?: string` to both interfaces:

```ts
export interface SkillItem {
  skill_id: string;
  label: string;
  description: string | null;
  inject_mode: 'auto' | 'prompt_only' | 'disabled';
  dependencies: string[];
  package?: string;
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
  package?: string;
}
```

- [ ] **Step 2: Run type-check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors (adding an optional field is backward-compatible)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add optional package field to SkillItem and SkillDetail types"
```

---

### Task 6: Frontend — Refactor SkillToggleGroup for Grouped Rendering

**Files:**
- Modify: `frontend/src/components/ui/SkillToggleGroup.tsx`
- Create: `frontend/src/components/ui/SkillToggleGroup.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ui/SkillToggleGroup.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SkillToggleGroup from './SkillToggleGroup';
import type { SkillItem } from '../../types';

describe('SkillToggleGroup grouping', () => {
  const skills: SkillItem[] = [
    { skill_id: 's1', label: 'Skill 1', description: null, inject_mode: 'auto', dependencies: [], package: 'aris' },
    { skill_id: 's2', label: 'Skill 2', description: null, inject_mode: 'auto', dependencies: [], package: 'aris' },
    { skill_id: 's3', label: 'Skill 3', description: null, inject_mode: 'auto', dependencies: [] },
  ];

  it('renders group headers for packaged skills', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText('aris')).toBeInTheDocument();
    expect(screen.getByText('未分组')).toBeInTheDocument();
  });

  it('toggles all skills in a group when group toggle is clicked', () => {
    const onChange = vi.fn();
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{ s1: 'disabled', s2: 'disabled' }}
        onChange={onChange}
      />
    );

    // Expand the aris group first (it's collapsed by default)
    const arisHeader = screen.getByText('aris').closest('div[class*="group-header"]') || screen.getByText('aris').parentElement;
    const chevron = arisHeader?.querySelector('[data-testid="chevron"]');
    if (chevron) fireEvent.click(chevron);

    const groupToggle = screen.getByText('aris').parentElement?.querySelector('button');
    if (groupToggle) fireEvent.click(groupToggle);

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ s1: 'enabled', s2: 'enabled' })
    );
  });

  it('expands and collapses groups via chevron', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    // aris group is collapsed by default — skills should not be visible
    expect(screen.queryByText('Skill 1')).not.toBeInTheDocument();

    // Click chevron to expand
    const chevron = screen.getByTestId('chevron-aris');
    fireEvent.click(chevron);

    expect(screen.getByText('Skill 1')).toBeInTheDocument();
    expect(screen.getByText('Skill 2')).toBeInTheDocument();
  });

  it('ungrouped bucket is expanded by default', () => {
    render(
      <SkillToggleGroup
        skills={skills}
        skillModes={{}}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText('Skill 3')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npm run test:run -- src/components/ui/SkillToggleGroup.test.tsx
```

Expected: FAIL — group headers not found, tests don't match current implementation

- [ ] **Step 3: Write implementation**

Replace the contents of `frontend/src/components/ui/SkillToggleGroup.tsx`:

```tsx
import { useMemo, useState } from 'react';
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

const buttonClass = (mode: SkillMode | 'mixed'): string => {
  switch (mode) {
    case 'enabled':
      return 'bg-[var(--apple-blue)] text-white';
    case 'auto':
      return 'bg-emerald-100 text-emerald-800';
    case 'mixed':
      return 'bg-amber-100 text-amber-800';
    case 'disabled':
    default:
      return 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)]';
  }
};

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

export default function SkillToggleGroup({ skills, skillModes, onChange }: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, SkillItem[]>();
    const ungrouped: SkillItem[] = [];

    for (const skill of skills) {
      if (skill.package) {
        const existing = map.get(skill.package) ?? [];
        existing.push(skill);
        map.set(skill.package, existing);
      } else {
        ungrouped.push(skill);
      }
    }

    const sorted = Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
    if (ungrouped.length > 0) {
      sorted.push(['未分组', ungrouped]);
    }
    return sorted;
  }, [skills]);

  const defaultExpanded = useMemo(() => {
    const map: Record<string, boolean> = {};
    for (const [name] of groups) {
      map[name] = name === '未分组';
    }
    return map;
  }, [groups]);

  const [expanded, setExpanded] = useState<Record<string, boolean>>(defaultExpanded);

  const cycleSkill = (skillId: string) => {
    const current = skillModes[skillId] ?? 'disabled';
    onChange({ ...skillModes, [skillId]: nextMode(current) });
  };

  const toggleGroup = (groupName: string, skillIds: string[]) => {
    const current = getGroupMode(skillModes, skillIds);
    let target: SkillMode;
    if (current === 'mixed') {
      target = 'enabled';
    } else {
      target = nextMode(current);
    }
    const updated = { ...skillModes };
    for (const id of skillIds) {
      updated[id] = target;
    }
    onChange(updated);
  };

  const toggleExpand = (groupName: string) => {
    setExpanded((prev) => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  return (
    <div className="space-y-3">
      {groups.map(([groupName, groupSkills]) => {
        const skillIds = groupSkills.map((s) => s.skill_id);
        const groupMode = getGroupMode(skillModes, skillIds);
        const isExpanded = expanded[groupName] ?? false;

        return (
          <div key={groupName} className="space-y-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => toggleGroup(groupName, skillIds)}
                className={[
                  'inline-flex items-center rounded-lg px-3 py-1.5 text-xs font-medium transition',
                  buttonClass(groupMode),
                ].join(' ')}
              >
                {groupMode === 'mixed' ? 'mixed' : groupMode}
              </button>
              <span className="text-sm font-medium text-[var(--text)]">{groupName}</span>
              <button
                type="button"
                onClick={() => toggleExpand(groupName)}
                data-testid={`chevron-${groupName}`}
                className="ml-auto text-[var(--text-secondary)] transition hover:text-[var(--text)]"
              >
                {isExpanded ? '▼' : '▶'}
              </button>
            </div>
            {isExpanded && (
              <div className="flex flex-wrap gap-2 pl-2">
                {groupSkills.map((skill) => {
                  const mode = skillModes[skill.skill_id] ?? 'disabled';
                  return (
                    <button
                      key={skill.skill_id}
                      type="button"
                      onClick={() => cycleSkill(skill.skill_id)}
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
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm run test:run -- src/components/ui/SkillToggleGroup.test.tsx
```

Expected: PASS

- [ ] **Step 5: Run type-check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/SkillToggleGroup.tsx frontend/src/components/ui/SkillToggleGroup.test.tsx
git commit -m "feat: refactor SkillToggleGroup with package grouping and expand/collapse"
```

---

### Task 7: Final Verification — Full Test Suites

**Files:**
- All modified files

- [ ] **Step 1: Run backend tests**

```bash
uv run pytest tests/skills/ tests/api/test_skills.py -v
```

Expected: ALL PASS

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm run test:run
```

Expected: ALL PASS (including new SkillToggleGroup tests)

- [ ] **Step 3: Run frontend type-check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 0 errors

- [ ] **Step 4: Commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address review feedback" || echo "No fixes needed"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| Add optional `package` field to backend schemas | Task 3 |
| Add `package` to `SkillDefinition` model | Task 1 |
| Pass `package` through discovery pipeline | Task 2 |
| Auto-populate `package="aris"` for ARIS/core skills | Task 4 |
| Add `package` to frontend types | Task 5 |
| Group skills by `package` in UI | Task 6 |
| Group-level toggle with mixed state | Task 6 |
| Expand/collapse with chevron | Task 6 |
| "未分组" bucket for skills without package | Task 6 |
| Ungrouped expanded by default, named groups collapsed | Task 6 |
| Individual skill toggle still works | Task 6 |
| Backward compatibility (optional field) | Tasks 1, 3, 5 |

## Placeholder Scan

No TBD, TODO, or placeholder text found.

## Type Consistency Check

- Backend: `package: str | None = None` used consistently across `SkillDefinition`, `SkillItem`, `SkillItemResponse`, `SkillDetailResponse`
- Frontend: `package?: string` used consistently across `SkillItem`, `SkillDetail`
- Generator: `package` read from frontmatter with fallback `"aris"` for core skills
