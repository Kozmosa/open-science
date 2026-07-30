# Design Spec: Detection Result Caching

> [!warning] Historical specification
> 本文已归档，不再定义当前产品 contract。请以 `PROJECT_BASIS.md`、`docs-site/docs/`、代码与活跃 spec 为准；原文保留用于解释历史决策和迁移来源。

## Context

Currently, `InMemoryEnvironmentService` stores detection results in `_detections:
dict[str, list[DetectionSnapshot]]` — an in-memory dict that is lost on service
restart. After each detection, results should be persisted to the state root so
they survive restarts.

## Changes

### 1. Persist detection snapshots to disk

After each successful detection (`detect_environment`), write the
`DetectionSnapshot` as JSON to `{state_root}/detections/{environment_id}.json`.

**File:** `src/ainrf/environments/service.py`

In `detect_environment()`:
- After `_write_back_detected_runtime_config()`, write the snapshot to disk
- Path: `self._state_root / "detections" / f"{environment_id}.json"`
- Store only the latest detection (overwrite, not append)

### 2. Load persisted detections on startup

In `InMemoryEnvironmentService.__init__()`:
- Scan `{state_root}/detections/*.json`
- Load each file, parse as `DetectionSnapshot`, populate `_detections` dict
- Skip files that fail to parse (log warning)

### 3. No API changes

The existing `GET /environments` and `GET /environments/{id}` responses already
include `latest_detection`. No API schema changes needed.

## Files

| File | Action |
|------|--------|
| `src/ainrf/environments/service.py` | Add persistence + loading logic |

## Verification

1. Backend tests: `uv run pytest tests/ -q`
2. Manual: run detection → restart service → check that detection data is still shown
3. Manual: check `~/.ainrf/detections/env-localhost.json` exists with valid JSON
