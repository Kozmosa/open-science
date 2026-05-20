# Detection Modal Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the detection modal: show SSH/Tmux as available/unavailable, replace code-server probe with Codex, fix GPU multi-model layout, add collapsible warnings section.

**Architecture:** Backend changes (probing.py, models.py, schemas.py) add tmux_ok and codex fields to the detection data. Frontend changes (types, detection modal component, i18n) update the UI to use them.

**Tech Stack:** Python 3.14, React 19, TypeScript, Tailwind CSS v4

**Spec:** `docs/superpowers/specs/2026-05-13-detection-modal-improvements-design.md`

---

### Task 1: Backend — add tmux_ok and codex to DetectionSnapshot

**Files:**
- Modify: `src/ainrf/environments/models.py`
- Modify: `src/ainrf/environments/probing.py`

- [ ] **Step 1: Add tmux_ok and codex fields to DetectionSnapshot**

In `src/ainrf/environments/models.py`, add to `DetectionSnapshot`:

```python
tmux_ok: bool = False
codex: ToolStatus = field(default_factory=lambda: ToolStatus(available=False, version=None, path=None))
```

- [ ] **Step 2: Set tmux_ok during probing**

In `src/ainrf/environments/probing.py`, in `build_detection_snapshot()`:
- `tmux_ok` is `True` when `ssh_ok` is `True` (we probed via SSH, tmux was accessible). When `ssh_ok` is `False`, check if `used_personal_tmux_fallback` is NOT in warnings — if the fallback was used, tmux is available via the fallback; otherwise it's unavailable.

Actually, simpler logic: `tmux_ok = not any(w == "ssh_unavailable" and "used_personal_tmux_fallback" in warnings)` — no, let me think again.

The user wants: if detection used personal tmux fallback, tmux is "unavailable" (because the normal tmux access failed). If detection succeeded via SSH, tmux is "available".

Simplest: `tmux_ok = ssh_ok` (SSH access implies tmux access; fallback means tmux was needed but SSH failed).

Add `tmux_ok=ssh_ok` to the `DetectionSnapshot(...)` constructor call at the end of `build_detection_snapshot()`.

- [ ] **Step 3: Add Codex probe**

In `build_detection_snapshot()`, replace the code-server probe call with a Codex probe. Add a new function `_probe_codex()` modeled after `_probe_claude()` (or reuse the existing tool probing pattern):

```python
async def _probe_codex(runner: ProbeCommandRunner) -> ToolStatus:
    """Check codex CLI availability."""
    return await _probe_tool(runner, "codex", "--version")
```

In `build_detection_snapshot()`, replace:
```python
code_server=await _probe_code_server(runner, code_server_path),
```
with:
```python
codex=await _probe_codex(runner),
```

Keep `code_server` in the DetectionSnapshot for backward compatibility but set it to a default unavailable ToolStatus. Or remove it entirely — since the spec says "Remove code_server_path probe and code-server tool check from the system", let me remove it.

Remove `code_server_path` parameter from `build_detection_snapshot()`. Remove the `_probe_code_server()` function. Remove `code_server` field from `DetectionSnapshot`.

Actually, removing a field from a dataclass will break serialization. Let me add `codex` and mark `code_server` as deprecated but keep it. The spec says "remove" but we can do a softer approach — just don't populate it from probing and show Codex in the UI instead.

Simpler approach per the spec: add `codex: ToolStatus`, remove `code_server` from DetectionSnapshot and all its usages.

- [ ] **Step 4: Type check and run backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/environments/models.py src/ainrf/environments/probing.py
git commit -m "feat: add tmux_ok and codex fields to detection, remove code_server probe"
```

---

### Task 2: Backend — update API schemas

**Files:**
- Modify: `src/ainrf/api/schemas.py`

- [ ] **Step 1: Add tmux_ok and codex to EnvironmentDetectionResponse**

In `src/ainrf/api/schemas.py`, in `EnvironmentDetectionResponse` (around line 188), add:

```python
tmux_ok: bool = False
codex: ToolStatusResponse | None = None
```

Remove or deprecate `code_server` field.

- [ ] **Step 2: Update serialization**

In `src/ainrf/api/routes/environments.py`, in `_serialize_environment()` (around line 35), update the dict construction to include `tmux_ok` and `codex` from the detection snapshot.

- [ ] **Step 3: Run backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/api/schemas.py src/ainrf/api/routes/environments.py
git commit -m "feat: add tmux_ok and codex to detection API response"
```

---

### Task 3: Frontend — update types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add tmux_ok and codex to EnvironmentDetection**

In `frontend/src/types/index.ts`, in `EnvironmentDetection` interface (around line 341), add:

```typescript
tmux_ok: boolean;
codex: ToolStatus;
```

Remove or keep `code_server` field (can keep for backward compat, UI just won't use it).

- [ ] **Step 2: Type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add tmux_ok and codex to frontend detection types"
```

---

### Task 4: Frontend — update mock detection data

**Files:**
- Modify: `frontend/src/api/mock.ts`

- [ ] **Step 1: Update createMockDetection**

In `createMockDetection()` (around line 451), add:

```typescript
tmux_ok: !environment.is_seed,
codex: createToolStatus(!environment.is_seed, '0.130.0', '/usr/bin/codex'),
```

- [ ] **Step 2: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/mock.ts
git commit -m "test: update mock detection with tmux_ok and codex"
```

---

### Task 5: Frontend — update detection modal UI

**Files:**
- Modify: `frontend/src/components/environment/EnvironmentDetectionModal.tsx`
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/messages.ts`, add to `components.environmentDetectionModal.labels`:

EN:
```ts
tmux: 'Tmux',
codex: 'Codex',
```

ZH:
```ts
tmux: 'Tmux',
codex: 'Codex',
```

Add to `components.environmentDetectionModal`:

EN:
```ts
warningsHeader: 'Warnings',
```

ZH:
```ts
warningsHeader: '告警',
```

- [ ] **Step 2: Update SSH row to show available/unavailable**

In the "Basic Info" GroupCard, the SSH row currently uses status color mapping (success/failed). Change to use the same `ToolStatusRow` pattern as other items, passing `detection.ssh_ok` as the available flag:

```tsx
<ToolStatusRow
  label={t('components.environmentDetectionModal.labels.ssh')}
  available={detection.ssh_ok}
  version={null}
/>
```

- [ ] **Step 3: Add Tmux row below SSH**

```tsx
<ToolStatusRow
  label={t('components.environmentDetectionModal.labels.tmux')}
  available={detection.tmux_ok}
  version={null}
/>
```

- [ ] **Step 4: Replace code-server with Codex**

In the "Dev Tools" GroupCard, replace the code-server `ToolStatusRow` with:

```tsx
<ToolStatusRow
  label={t('components.environmentDetectionModal.labels.codex')}
  available={detection.codex.available}
  version={detection.codex.version}
/>
```

- [ ] **Step 5: Fix GPU model layout for multiple GPUs**

In the "GPU Info" GroupCard, change the GPU models display:

```tsx
{detection.gpu_count > 1 ? (
  <>
    <InfoRow label={t('components.environmentDetectionModal.labels.gpuModels')} value={null} />
    {detection.gpu_models.map((model, i) => (
      <div key={i} className="text-sm text-[var(--text)]">{model}</div>
    ))}
    <InfoRow label={t('components.environmentDetectionModal.labels.gpuCount')} value={String(detection.gpu_count)} />
  </>
) : (
  <>
    <InfoRow label={t('components.environmentDetectionModal.labels.gpuModels')} value={detection.gpu_models[0] ?? null} />
    <InfoRow label={t('components.environmentDetectionModal.labels.gpuCount')} value={String(detection.gpu_count)} />
  </>
)}
```

- [ ] **Step 6: Replace flat warnings with collapsible section**

Replace the flat `<Alert>` list for warnings (currently lines 197-205) with a collapsible section:

```tsx
{detection.warnings.length > 0 && (
  <details className="rounded-xl border border-amber-200 bg-amber-50 p-4">
    <summary className="cursor-pointer text-sm font-medium text-amber-800">
      {t('components.environmentDetectionModal.warningsHeader')} ({detection.warnings.length})
    </summary>
    <div className="mt-3 space-y-2">
      {detection.warnings.map((warning, index) => (
        <Alert key={index} variant="warning">{warning}</Alert>
      ))}
    </div>
  </details>
)}
```

The `<details>` element provides native collapsible behavior without additional state.

- [ ] **Step 7: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b && npm run test:run 2>&1 | tail -5
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/environment/EnvironmentDetectionModal.tsx frontend/src/i18n/messages.ts
git commit -m "feat: improve detection modal (SSH/Tmux status, Codex, GPU layout, collapsible warnings)"
```
