# Design Spec: Detection Modal Improvements

## Context

The environment detection modal shows probe results in grouped cards. Several
improvements are needed to make the information more useful and compact.

## Changes

### 1. SSH status: show available/unavailable instead of failed

In the "Basic Info" group card, SSH status currently shows "成功/Success" or
"失败/Failed" based on `ssh_ok`. Change to show:
- `ssh_ok === true` → green dot + "可用 / Available"
- `ssh_ok === false` → red/amber dot + "不可用 / Unavailable"

Same style as other `ToolStatusRow` items (available/unavailable with color).

### 2. Add Tmux status row

Below the SSH row in "Basic Info", add a Tmux row:
- Same `ToolStatusRow` style as other items
- Status derived from detection warnings: if `warnings` does NOT include
  `"used_personal_tmux_fallback"`, tmux is "可用 / Available"; otherwise
  "不可用 / Unavailable" (since we had to fall back to personal tmux)
- Backend: add `tmux_ok: bool` to `DetectionSnapshot` (derived during probing)
- Frontend: add `tmux_ok: boolean` to `EnvironmentDetection` type

### 3. Replace code-server with Codex

In the "Dev Tools" group card:
- Remove the code-server `ToolStatusRow`
- Add a Codex `ToolStatusRow` instead
- Backend: in `build_detection_snapshot()`, replace `_probe_code_server()` call
  with a Codex probe: `codex --version` + `command -v codex`
- Add `codex: ToolStatus` to `DetectionSnapshot`
- Frontend: replace `code_server` with `codex: ToolStatus` in `EnvironmentDetection`
- Update i18n keys: add `components.environmentDetectionModal.labels.codex`
- Remove `code_server_path` probe and `code-server` tool check from the system

### 4. GPU model layout: one model per line

In the "GPU Info" group card:
- When `gpu_count > 1`: show "GPU 型号 / GPU Models" label on its own line,
  then each GPU model on a separate line below
- When `gpu_count === 1`: show as before (model inline with label)
- When `gpu_count === 0`: show "—" as before

Frontend change only (backend already returns `gpu_models: string[]`).

### 5. Collapsible warnings section

Replace the flat list of warning `<Alert>` components with a single collapsible
section:

```
┌─────────────────────────────────────┐
│ 告警 / Warnings (2)        ▼/▶     │  ← collapsible header, default collapsed
├─────────────────────────────────────┤
│ ⚠ ssh_unavailable                  │
│ ⚠ used_personal_tmux_fallback      │
└─────────────────────────────────────┘
```

- Header text: i18n `components.environmentDetectionModal.warningsHeader`
  (EN: "Warnings", ZH: "告警")
- Shows count of warnings in header (e.g., "告警 (2)")
- Default collapsed (`defaultExpanded={false}` or internal state starting false)
- Chevron icon toggles expand/collapse
- Each warning rendered as before (Alert variant="warning")

## Files

| File | Action |
|------|--------|
| `src/ainrf/environments/probing.py` | Add tmux_ok, codex probe, remove code-server |
| `src/ainrf/environments/models.py` | Add tmux_ok, codex to DetectionSnapshot |
| `src/ainrf/api/schemas.py` | Add tmux_ok, codex to response models |
| `frontend/src/types/index.ts` | Add tmux_ok, codex to EnvironmentDetection |
| `frontend/src/components/environment/EnvironmentDetectionModal.tsx` | All UI changes |
| `frontend/src/i18n/messages.ts` | Add codex label, warningsHeader, tmux label |
| `frontend/src/api/mock.ts` | Update mock detection data |

## Verification

1. Backend tests: `uv run pytest tests/ -q`
2. Frontend: `cd frontend && node_modules/.bin/tsc -b && npm run test:run`
3. Manual: run detection → open modal → verify SSH/Tmux show available/unavailable
4. Manual: verify Codex row appears (not code-server)
5. Manual: with multi-GPU → verify each GPU on its own line
6. Manual: warnings are collapsed by default, expandable
