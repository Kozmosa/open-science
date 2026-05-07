# Research Modes (Reproduce / Discover / Validate) Design

> **Scope:** Feat 1 of RD-new — extend `TaskConfigurationMode` with three ARIS-powered research modes.

---

## Goal

Add three new task configuration modes that leverage installed ARIS skills to perform automated research workflows: baseline reproduction, idea discovery, and idea validation. If required ARIS skills are missing, the system rejects task creation with a clear error.

## Architecture

Extend the existing `TaskConfigurationMode` union and `TaskConfigurationPreset` list. Each new mode reuses the existing `template_vars` dictionary for mode-specific inputs. The backend routes prompt rendering by mode. ARIS skill availability is checked at task creation time.

## Data Model

### `TaskConfigurationMode` (frontend + backend)

```ts
type TaskConfigurationMode =
  | 'raw_prompt'
  | 'structured_research'
  | 'reproduce_baseline'
  | 'discover_ideas'
  | 'validate_ideas';
```

Backend `TaskConfigurationMode` enum (Pydantic / Python) is updated with the same three new variants.

### Default Presets

Three new presets added to `createDefaultTaskConfigurations()`:

| configId | label | mode |
|----------|-------|------|
| `reproduce-baseline-default` | Reproduce Baseline | `reproduce_baseline` |
| `discover-ideas-default` | Discover IDEAs | `discover_ideas` |
| `validate-ideas-default` | Validate IDEAs | `validate_ideas` |

### `template_vars` per Mode

All modes reuse the existing `template_vars: dict[str, object]` field in `TaskConfigurationSnapshot`.

**Reproduce Baseline**
- `paper_path` (string, required) — path to PDF in workspace
- `scope` (string, optional, default `"core-only"`) — `"core-only"` or `"full-suite"`
- `target_table` (string, optional) — specific table/figure to reproduce
- `budget_hours` (number, optional, default `4`) — GPU hour budget

**Discover IDEAs**
- `topic` (string, required) — research direction / question
- `seed_paper_path` (string, optional) — path to seed PDF in workspace
- `depth` (number, optional, default `3`) — max recursion depth for reference expansion
- `budget_hours` (number, optional, default `4`) — time budget

**Validate IDEAs**
- `idea_source` (string, required) — path to idea doc in workspace OR inline description
- `validation_scope` (string, optional, default `"full"`) — `"quick"` or `"full"`
- `budget_hours` (number, optional, default `4`)

## Prompt Rendering

Replace `_render_structured_research_prompt` with `_render_task_prompt(task_input: str, mode: TaskConfigurationMode, template_vars: dict[str, object]) -> str`.

**Reproduce Baseline**
```
/research-pipeline "{{paper_path}}" --scope {{scope}} {% if target_table %}--target {{target_table}}{% endif %} --budget {{budget_hours}}

Reproduce the target paper. Parse the PDF, implement the core method, run experiments, and compare results against the paper's reported values.
```

**Discover IDEAs**
```
/research-lit "{{topic}}" {% if seed_paper_path %}--seed {{seed_paper_path}}{% endif %} --depth {{depth}} --budget {{budget_hours}}

Discover novel research ideas by surveying the literature, analyzing the seed paper (if provided), and generating concrete, feasible research proposals.
```

**Validate IDEAs**
```
/research-refine-pipeline "{{idea_source}}" --scope {{validation_scope}} --budget {{budget_hours}}

Validate the given research idea. Design experiments, run pilots, analyze feasibility, and produce a validation report.
```

## ARIS Skill Detection

In `TaskHarnessService.create_task()`, before writing artifacts:

```python
_ARIS_SKILL_REQUIREMENTS: dict[TaskConfigurationMode, list[str]] = {
    TaskConfigurationMode.REPRODUCE_BASELINE: ["research-pipeline"],
    TaskConfigurationMode.DISCOVER_IDEAS: ["research-lit"],
    TaskConfigurationMode.VALIDATE_IDEAS: ["research-refine-pipeline"],
}

def _check_aris_skills(mode: TaskConfigurationMode, skill_root: Path) -> None:
    required = _ARIS_SKILL_REQUIREMENTS.get(mode)
    if not required:
        return
    missing = [s for s in required if not (skill_root / s).exists()]
    if missing:
        raise TaskHarnessError(
            f"ARIS skill(s) not installed: {', '.join(missing)}. "
            f"Install via Settings > Skill Repository before using {mode.value} mode."
        )
```

Error propagates to API as HTTP 400 with the message surfaced in the UI.

## UI Changes

### `TaskCreateForm.tsx`

- `TaskConfiguration` select: add three new options
- Conditional form fields below the select, keyed by `selectedTaskConfiguration.mode`:
  - `reproduce_baseline`: Paper path input, scope select, target table input, budget input
  - `discover_ideas`: Topic textarea, seed paper path input, depth input, budget input
  - `validate_ideas`: Idea source textarea (placeholder: "Path to idea doc or describe your idea..."), scope select, budget input

### `SettingsPage.tsx`

- Default `taskConfigurations` array includes the three new presets

## Error Handling

- Missing ARIS skill → `TaskHarnessError` at `create_task` → API 400 → UI toast/error banner
- Invalid template_vars (e.g., missing required `paper_path`) → validated in `create_task` before persistence
- Prompt rendering failure → fallback to raw task input with a warning log

## Testing

- Backend: test `_check_aris_skills` with missing/present skills
- Backend: test `_render_task_prompt` for each mode with full and minimal template_vars
- Frontend: test mode switching in TaskCreateForm renders correct fields
- Frontend: test storage round-trip for new mode presets
- Integration: test API rejects task creation when ARIS skill missing

## Non-Goals

- Does NOT auto-install ARIS skills on demand
- Does NOT validate that `paper_path` or `seed_paper_path` actually exist in the workspace (ARIS skill handles that)
- Does NOT add per-mode progress dashboards (reuse existing task output streaming)
