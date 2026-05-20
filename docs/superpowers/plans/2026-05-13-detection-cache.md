# Detection Result Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the latest detection snapshot for each environment to disk so detection results survive service restarts.

**Architecture:** After each successful detection, write the `DetectionSnapshot` as JSON to `{state_root}/detections/{env_id}.json`. On service initialization, scan the detections directory and load all persisted snapshots into the in-memory `_detections` dict.

**Tech Stack:** Python 3.14, dataclasses, pathlib, json

**Spec:** `docs/superpowers/specs/2026-05-13-detection-cache-design.md`

---

### Task 1: Add persistence on detection

**Files:**
- Modify: `src/ainrf/environments/service.py`

- [ ] **Step 1: Read the current detect_environment method**

Read `/home/xuyang/code/scholar-agent/src/ainrf/environments/service.py` lines 247-290 to understand `detect_environment()` flow.

- [ ] **Step 2: Add _persist_detection method**

Add to `InMemoryEnvironmentService`:

```python
def _persist_detection(self, environment_id: str, snapshot: DetectionSnapshot) -> None:
    detections_dir = self._state_root / "detections"
    detections_dir.mkdir(parents=True, exist_ok=True)
    filepath = detections_dir / f"{environment_id}.json"
    data = {
        "environment_id": snapshot.environment_id,
        "detected_at": snapshot.detected_at.isoformat(),
        "status": snapshot.status.value,
        "summary": snapshot.summary,
        "errors": snapshot.errors,
        "warnings": snapshot.warnings,
        "ssh_ok": snapshot.ssh_ok,
        "hostname": snapshot.hostname,
        "os_info": snapshot.os_info,
        "arch": snapshot.arch,
        "workdir_exists": snapshot.workdir_exists,
        "python": _tool_status_to_dict(snapshot.python),
        "conda": _tool_status_to_dict(snapshot.conda),
        "uv": _tool_status_to_dict(snapshot.uv),
        "pixi": _tool_status_to_dict(snapshot.pixi),
        "code_server": _tool_status_to_dict(snapshot.code_server),
        "torch": _tool_status_to_dict(snapshot.torch),
        "cuda": _tool_status_to_dict(snapshot.cuda),
        "gpu_models": snapshot.gpu_models,
        "gpu_count": snapshot.gpu_count,
        "claude_cli": _tool_status_to_dict(snapshot.claude_cli),
        "anthropic_env": snapshot.anthropic_env.value if snapshot.anthropic_env else None,
    }
    filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
```

And a module-level helper:

```python
def _tool_status_to_dict(ts: ToolStatus) -> dict:
    return {"available": ts.available, "version": ts.version, "path": ts.path}
```

- [ ] **Step 3: Call _persist_detection after successful detection**

In `detect_environment()`, after the detection succeeds (status is not FAILED), add:

```python
if snapshot.status != DetectionStatus.FAILED:
    self._persist_detection(environment_id, snapshot)
```

- [ ] **Step 4: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/environments/service.py
git commit -m "feat: persist detection results to disk"
```

---

### Task 2: Load persisted detections on startup

**Files:**
- Modify: `src/ainrf/environments/service.py`

- [ ] **Step 1: Add _load_persisted_detections method**

Add to `InMemoryEnvironmentService.__init__` or as a method called from `__init__`:

```python
def _load_persisted_detections(self) -> None:
    detections_dir = self._state_root / "detections"
    if not detections_dir.is_dir():
        return
    for filepath in detections_dir.glob("*.json"):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            env_id = data["environment_id"]
            snapshot = DetectionSnapshot(
                environment_id=env_id,
                detected_at=datetime.fromisoformat(data["detected_at"]),
                status=DetectionStatus(data["status"]),
                summary=data.get("summary", ""),
                errors=data.get("errors", []),
                warnings=data.get("warnings", []),
                ssh_ok=data.get("ssh_ok", False),
                hostname=data.get("hostname"),
                os_info=data.get("os_info"),
                arch=data.get("arch"),
                workdir_exists=data.get("workdir_exists"),
                python=_dict_to_tool_status(data.get("python", {})),
                conda=_dict_to_tool_status(data.get("conda", {})),
                uv=_dict_to_tool_status(data.get("uv", {})),
                pixi=_dict_to_tool_status(data.get("pixi", {})),
                code_server=_dict_to_tool_status(data.get("code_server", {})),
                torch=_dict_to_tool_status(data.get("torch", {})),
                cuda=_dict_to_tool_status(data.get("cuda", {})),
                gpu_models=data.get("gpu_models", []),
                gpu_count=data.get("gpu_count", 0),
                claude_cli=_dict_to_tool_status(data.get("claude_cli", {})),
                anthropic_env=AnthropicEnvStatus(data["anthropic_env"]) if data.get("anthropic_env") else None,
            )
            self._detections[env_id].append(snapshot)
        except Exception:
            logger.warning("Failed to load persisted detection from %s", filepath, exc_info=True)
```

And a module-level helper:

```python
def _dict_to_tool_status(d: dict) -> ToolStatus:
    return ToolStatus(
        available=d.get("available", False),
        version=d.get("version"),
        path=d.get("path"),
    )
```

- [ ] **Step 2: Call _load_persisted_detections from __init__**

In `InMemoryEnvironmentService.__init__()`, after initializing `self._detections`, add:

```python
self._load_persisted_detections()
```

Note: `self._state_root` must already be set. Check that `__init__` receives or computes it. If `_state_root` is not stored on the instance, add `self._state_root = state_root` in `__init__`.

- [ ] **Step 3: Type check and run tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/environments/service.py
git commit -m "feat: load persisted detections on startup"
```
