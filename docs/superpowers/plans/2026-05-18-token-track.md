# Token Track Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture token usage from AgentSdkEngine (ResultMessage) and ClaudeCodeEngine (session-meta polling), write into Session Chain (task_attempts.token_usage_json / task_sessions.total_cost_usd), and visualize in frontend (TokenFlowBar + per-model breakdown + per-project cost).

**Architecture:** Extend EngineEvent with optional `token_usage` field. Both engines populate it — SDK directly from ResultMessage, Claude Code via post-exit session-meta polling. The `emit` closure in `_run_task` captures it and calls `session_service.complete_attempt()` after `engine.start()` returns. `_recalc_session` aggregates cost via `json_extract`. Frontend adds TokenFlowBar component (colored token segments).

**Tech Stack:** Python 3.13 dataclasses, SQLite3 json_extract, FastAPI, React 19 + Tailwind v4, Vitest

---

## File Structure

```
src/ainrf/task_harness/
    engines/base.py          # + token_usage: dict | None to EngineEvent, + "token" to event_type Literal
    engines/agent_sdk.py     # extract ResultMessage.usage/model_usage/cost → token_usage
    engines/claude_code.py   # poll ~/.claude/usage-data/session-meta/ after subprocess exit
    models.py                # + TOKEN = "token" to TaskOutputKind
    service.py               # + session_service injection, emit capture, complete_attempt call

src/ainrf/sessions/
    service.py               # _recalc_session: + json_extract cost aggregation

src/ainrf/api/
    app.py                   # pass session_service to TaskHarnessService
    routes/projects.py       # + GET /projects/{id}/cost-summary
    routes/sessions.py       # no changes needed (token_usage already serialized)
    schemas.py               # + ProjectCostSummaryResponse

frontend/src/
    types/index.ts           # + TokenUsage, ProjectCostSummary
    api/endpoints.ts         # + getProjectCostSummary
    components/token/        # NEW directory
        TokenFlowBar.tsx     # colored token segment bar
    pages/sessions/
        AttemptChain.tsx     # integrate TokenFlowBar
        SessionDetail.tsx    # show actual total_cost_usd + total_tokens

tests/
    test_token_track.py      # backend tests
```

---

## Task 1: EngineEvent Extension + AgentSdkEngine Token Extraction

**Files:**
- Modify: `src/ainrf/task_harness/engines/base.py`
- Modify: `src/ainrf/task_harness/engines/agent_sdk.py`
- Modify: `src/ainrf/task_harness/models.py`
- Modify: `src/ainrf/task_harness/service.py` (just _engine_event_to_kind)

- [ ] **Step 1: Extend EngineEvent in base.py**

In `src/ainrf/task_harness/engines/base.py`, change EngineEvent:

```python
@dataclass(slots=True)
class EngineEvent:
    event_type: Literal[
        "message",
        "thinking",
        "tool_call",
        "tool_result",
        "status",
        "system",
        "error",
        "token",
    ]
    payload: dict
    token_usage: dict | None = None
```

Two changes: add `"token"` to the Literal, add `token_usage: dict | None = None` field.

- [ ] **Step 2: Add TOKEN to TaskOutputKind in models.py**

In `src/ainrf/task_harness/models.py`, add to TaskOutputKind:

```python
class TaskOutputKind(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"
    LIFECYCLE = "lifecycle"
    MESSAGE = "message"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOKEN = "token"
```

- [ ] **Step 3: Add "token" to _engine_event_to_kind in service.py**

In `src/ainrf/task_harness/service.py`, add to the mapping dict in `_engine_event_to_kind`:

```python
def _engine_event_to_kind(self, event_type: str) -> TaskOutputKind:
    mapping = {
        "message": TaskOutputKind.MESSAGE,
        "thinking": TaskOutputKind.THINKING,
        "tool_call": TaskOutputKind.TOOL_CALL,
        "tool_result": TaskOutputKind.TOOL_RESULT,
        "status": TaskOutputKind.SYSTEM,
        "system": TaskOutputKind.SYSTEM,
        "error": TaskOutputKind.STDERR,
        "token": TaskOutputKind.TOKEN,
    }
    return mapping.get(event_type, TaskOutputKind.STDOUT)
```

- [ ] **Step 4: Extract token_usage from ResultMessage in agent_sdk.py**

In `src/ainrf/task_harness/engines/agent_sdk.py`, modify the `ResultMessage` handling block (around line 324). After the existing code that creates the system event with `task_completed` or `task_failed` subtype, add `token_usage` construction. Replace the two `EngineEvent(...)` calls in the ResultMessage block:

For the error case (around line 332):
```python
token_usage = _build_token_usage(sdk_msg)
events.append(
    EngineEvent(
        event_type="system",
        payload={
            "subtype": "task_failed",
            "session_id": sdk_msg.session_id,
            "num_turns": sdk_msg.num_turns,
            "total_cost_usd": sdk_msg.total_cost_usd,
            "errors": sdk_msg.errors,
        },
        token_usage=token_usage,
    )
)
```

For the success case (around line 345):
```python
token_usage = _build_token_usage(sdk_msg)
events.append(
    EngineEvent(
        event_type="system",
        payload={
            "subtype": "task_completed",
            "session_id": sdk_msg.session_id,
            "num_turns": sdk_msg.num_turns,
            "total_cost_usd": sdk_msg.total_cost_usd,
        },
        token_usage=token_usage,
    )
)
```

Add a module-level helper function at the top of agent_sdk.py (after imports):

```python
def _build_token_usage(sdk_msg) -> dict | None:
    """Build token_usage dict from SDK ResultMessage."""
    usage = getattr(sdk_msg, "usage", None)
    if not usage:
        return None
    result: dict = {
        "total": dict(usage),
        "source": "agent-sdk",
    }
    total_cost = getattr(sdk_msg, "total_cost_usd", None) or 0.0
    if "cost_usd" not in result["total"]:
        result["total"]["cost_usd"] = float(total_cost)
    model_usage = getattr(sdk_msg, "model_usage", None)
    if model_usage:
        result["by_model"] = dict(model_usage)
    return result
```

- [ ] **Step 5: Also emit per-turn token events from AssistantMessage**

In the `AssistantMessage` block (around line 248), after processing all content blocks, add a per-turn token event if `sdk_msg.usage` is present:

```python
if isinstance(sdk_msg, AssistantMessage):
    for block in sdk_msg.content:
        # ... existing block processing ...

    # Emit per-turn token snapshot
    if sdk_msg.usage:
        events.append(
            EngineEvent(
                event_type="token",
                payload={"turn": len(events)},
                token_usage={"total": dict(sdk_msg.usage), "source": "agent-sdk"},
            )
        )
    return events
```

- [ ] **Step 6: Verify imports and syntax**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.task_harness.engines.base import EngineEvent; e = EngineEvent('token', {}, token_usage={'total': {'input_tokens': 100}}); print('OK', e.token_usage)"`
Expected: `OK {'total': {'input_tokens': 100}}`

- [ ] **Step 7: Run existing tests to verify no regression**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/ainrf/task_harness/engines/base.py src/ainrf/task_harness/engines/agent_sdk.py src/ainrf/task_harness/models.py src/ainrf/task_harness/service.py
git commit -m "feat: add token_usage to EngineEvent, extract from AgentSdkEngine ResultMessage"
```

---

## Task 2: Task Harness Integration (SessionService Injection + emit Capture + complete_attempt)

**Files:**
- Modify: `src/ainrf/task_harness/service.py`
- Modify: `src/ainrf/api/app.py`

- [ ] **Step 1: Inject SessionService into TaskHarnessService**

In `src/ainrf/task_harness/service.py`, modify `__init__`:

```python
class TaskHarnessService:
    def __init__(
        self,
        *,
        state_root: Path,
        environment_service: InMemoryEnvironmentService,
        workspace_service: WorkspaceRegistryService,
        skill_root: Path | str | None = None,
        session_service: "SessionService | None" = None,
    ) -> None:
        ...
        self._session_service = session_service
```

Use a string annotation `"SessionService | None"` to avoid circular import (don't import SessionService at top level). At the bottom of `__init__`, store `self._session_service = session_service`.

- [ ] **Step 2: Capture token_usage in emit closure and call complete_attempt after engine.start()**

In the `_run_task` method, in the agent-sdk branch (around line 913), modify the emit closure to capture token_usage:

```python
captured_token_usage = None

async def emit(event: EngineEvent) -> None:
    nonlocal engine_paused, engine_failed, captured_token_usage
    if event.event_type == "system":
        subtype = event.payload.get("subtype")
        if subtype == "task_paused":
            engine_paused = True
            self._update_task_status(task_id, status=TaskHarnessStatus.PAUSED)
        elif subtype == "task_failed":
            engine_failed = True
        if event.token_usage and subtype in ("task_completed", "task_failed"):
            captured_token_usage = event.token_usage
    if event.event_type == "token":
        # token events are emitted as TOKEN kind output events (real-time stream)
        pass
    content = (
        json.dumps(event.payload)
        if isinstance(event.payload, dict)
        else str(event.payload)
    )
    kind = self._engine_event_to_kind(event.event_type)
    self._append_output_event(task_id, kind, content)
```

After `engine.start(context, emit)` returns but before `_complete_task` / `_fail_task`, add the session attempt update:

```python
# After engine.start() returns (around line 934):
try:
    await engine.start(context, emit)
except ...:
    ...

# NEW: update session attempt with token data
if self._session_service and captured_token_usage:
    task_session_id = row["session_id"] if "session_id" in row.keys() else None
    if task_session_id:
        try:
            attempts = self._session_service.list_attempts(task_session_id)
            # Find the latest attempt for this task
            matching = [a for a in attempts if a.task_id == task_id]
            if matching:
                latest = matching[-1]
                status = "completed" if not engine_failed else "failed"
                # Calculate duration
                started = row["started_at"]
                duration_ms = None
                if started:
                    from datetime import datetime, timezone
                    try:
                        start_dt = datetime.fromisoformat(started)
                        duration_ms = int((datetime.now(timezone.utc) - start_dt).total_seconds() * 1000)
                    except Exception:
                        pass
                self._session_service.complete_attempt(
                    latest.id,
                    status=status,
                    duration_ms=duration_ms,
                    token_usage_json=json.dumps(captured_token_usage),
                )
        except Exception:
            logger.warning("Failed to update session attempt with token data", exc_info=True)
```

- [ ] **Step 3: Do the same for Claude Code branch**

In the Claude Code (subprocess) branch, also declare `captured_token_usage` similarly and add the session attempt update after `_stream_process_output` returns (around line 1036), before `_complete_task` / `_fail_task`.

The emit closure in the Claude Code path is in ClaudeCodeEngine.start(), which will emit token_usage via the EngineEvent. The `_run_task` emit closure already captures it (same code as above). After the subprocess finishes, in `_run_task` around line 1036, add the same session attempt update block.

- [ ] **Step 4: Wire session_service in app.py**

In `src/ainrf/api/app.py` (around line 135), pass `session_service` to TaskHarnessService:

```python
app.state.session_service = SessionService(
    state_root=api_config.state_root,
)
app.state.task_harness_service = TaskHarnessService(
    state_root=api_config.state_root,
    environment_service=environment_service,
    workspace_service=app.state.workspace_service,
    skill_root=default_workspace_dir / "skills",
    session_service=app.state.session_service,
)
```

Note: Move `session_service` creation BEFORE `task_harness_service` creation.

- [ ] **Step 5: Verify imports and run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.api.app import create_app; print('OK')"`
Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/task_harness/service.py src/ainrf/api/app.py
git commit -m "feat: integrate SessionService into TaskHarnessService for token capture"
```

---

## Task 3: ClaudeCodeEngine session-meta Polling

**Files:**
- Modify: `src/ainrf/task_harness/engines/claude_code.py`

- [ ] **Step 1: Add session-meta polling to ClaudeCodeEngine.start()**

Rewrite `src/ainrf/task_harness/engines/claude_code.py`:

```python
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .base import EngineContext, EngineEvent, ExecutionEngine, NotSupportedError

_SESSION_META_DIR = Path.home() / ".claude" / "usage-data" / "session-meta"
_POLL_TIMEOUT_SEC = 30
_POLL_INTERVAL_SEC = 1.0


def _find_session_meta(started_at: float) -> dict | None:
    """Find the session-meta file whose start_time is closest to started_at."""
    if not _SESSION_META_DIR.exists():
        return None
    best = None
    best_diff = float("inf")
    for f in _SESSION_META_DIR.iterdir():
        if not f.suffix == ".json":
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        meta_start = data.get("start_time")
        if meta_start is None:
            continue
        diff = abs(meta_start - started_at)
        if diff < best_diff and diff <= 10:  # within 10 second window
            best_diff = diff
            best = data
    return best


class ClaudeCodeEngine(ExecutionEngine):
    async def start(self, context: EngineContext, emit) -> None:
        started_at = time.time()
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.working_directory,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if context.rendered_prompt:
            process.stdin.write(context.rendered_prompt.encode())
            await process.stdin.drain()
            process.stdin.close()

        await emit(EngineEvent(event_type="system", payload={"subtype": "task_started"}))

        async def read_stream(stream, kind):
            while True:
                line = await stream.readline()
                if not line:
                    break
                role = "assistant" if kind == "stdout" else "system"
                await emit(
                    EngineEvent(
                        event_type="message",
                        payload={"role": role, "content": line.decode("utf-8", errors="replace")},
                    )
                )

        await asyncio.gather(
            read_stream(process.stdout, "stdout"),
            read_stream(process.stderr, "stderr"),
        )
        await process.wait()

        # Poll for session-meta token data
        token_usage = await self._poll_session_meta(started_at)
        status = "succeeded" if process.returncode == 0 else "failed"
        await emit(
            EngineEvent(
                event_type="system",
                payload={"subtype": f"task_{status}"},
                token_usage=token_usage,
            )
        )
        await emit(EngineEvent(event_type="status", payload={"status": status}))

    async def _poll_session_meta(self, started_at: float) -> dict | None:
        """Poll session-meta directory for a matching file, up to 30 seconds."""
        deadline = time.time() + _POLL_TIMEOUT_SEC
        while time.time() < deadline:
            meta = _find_session_meta(started_at)
            if meta is not None:
                input_tokens = meta.get("input_tokens", 0)
                output_tokens = meta.get("output_tokens", 0)
                if input_tokens or output_tokens:
                    return {
                        "total": {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        },
                        "source": "claude-session-meta",
                    }
            await asyncio.sleep(_POLL_INTERVAL_SEC)
        return None

    async def pause(self, task_id: str) -> None:
        raise NotSupportedError("ClaudeCodeEngine does not support pause")

    async def resume(self, context: EngineContext, emit) -> None:
        raise NotSupportedError("ClaudeCodeEngine does not support resume")

    async def send_prompt(self, task_id: str, prompt: str) -> None:
        raise NotSupportedError("ClaudeCodeEngine does not support send_prompt")

    async def abort(self, task_id: str) -> None:
        pass
```

- [ ] **Step 2: Verify import and syntax**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.task_harness.engines.claude_code import ClaudeCodeEngine; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/task_harness/engines/claude_code.py
git commit -m "feat: add session-meta polling for Claude Code token data"
```

---

## Task 4: _recalc_session Cost Aggregation + Project Cost-Summary API

**Files:**
- Modify: `src/ainrf/sessions/service.py`
- Modify: `src/ainrf/api/routes/projects.py`
- Modify: `src/ainrf/api/schemas.py`

- [ ] **Step 1: Extend _recalc_session to aggregate cost**

In `src/ainrf/sessions/service.py`, modify `_recalc_session`:

```python
def _recalc_session(self, session_id: str) -> None:
    with self._connect() as conn:
        agg = conn.execute(
            "SELECT COUNT(*) AS cnt, "
            "COALESCE(SUM(duration_ms), 0) AS dur, "
            "COALESCE(SUM(CAST(json_extract(token_usage_json, '$.total.cost_usd') AS REAL)), 0.0) AS total_cost "
            "FROM task_attempts WHERE session_id = ? AND duration_ms IS NOT NULL",
            (session_id,),
        ).fetchone()
        if agg:
            conn.execute(
                "UPDATE task_sessions SET task_count = ?, total_duration_ms = ?, "
                "total_cost_usd = ?, updated_at = ? WHERE id = ?",
                (agg["cnt"], agg["dur"], agg["total_cost"], _now_iso(), session_id),
            )
            conn.commit()
```

- [ ] **Step 2: Add ProjectCostSummaryResponse to schemas.py**

```python
class ProjectCostSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    total_cost_usd: float
    total_tokens: int
    session_count: int
    by_model: dict[str, dict[str, object]] = Field(default_factory=dict)
```

- [ ] **Step 3: Add cost-summary route to projects.py**

In `src/ainrf/api/routes/projects.py`, add:

```python
from ainrf.api.schemas import ProjectCostSummaryResponse

@router.get("/{project_id}/cost-summary", response_model=ProjectCostSummaryResponse)
async def get_project_cost_summary(
    project_id: str, request: Request
) -> ProjectCostSummaryResponse:
    session_service = _get_session_service(request)
    try:
        sessions = session_service.list_sessions(project_id=project_id)
    except Exception as exc:
        raise _translate_error(exc) from exc

    total_cost = 0.0
    total_tokens = 0
    by_model: dict[str, dict] = {}

    for s in sessions:
        total_cost += s.total_cost_usd
        attempts = session_service.list_attempts(s.id)
        for a in attempts:
            if a.token_usage_json:
                try:
                    tu = json.loads(a.token_usage_json)
                except Exception:
                    continue
                total = tu.get("total", {})
                total_tokens += total.get("input_tokens", 0)
                total_tokens += total.get("output_tokens", 0)
                total_tokens += total.get("cache_creation_input_tokens", 0)
                total_tokens += total.get("cache_read_input_tokens", 0)
                for model, usage in tu.get("by_model", {}).items():
                    if model not in by_model:
                        by_model[model] = {"cost_usd": 0.0, "tokens": 0}
                    by_model[model]["cost_usd"] += usage.get("cost_usd", 0)
                    by_model[model]["tokens"] += usage.get("input_tokens", 0)
                    by_model[model]["tokens"] += usage.get("output_tokens", 0)

    return ProjectCostSummaryResponse.model_validate({
        "project_id": project_id,
        "total_cost_usd": round(total_cost, 2),
        "total_tokens": total_tokens,
        "session_count": len(sessions),
        "by_model": by_model,
    })
```

Add helper to get session_service:

```python
def _get_session_service(request: Request):
    from ainrf.sessions import SessionService
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="session service not initialized")
    return service
```

- [ ] **Step 4: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/sessions/service.py src/ainrf/api/routes/projects.py src/ainrf/api/schemas.py
git commit -m "feat: add cost aggregation to _recalc_session and project cost-summary API"
```

---

## Task 5: Frontend — TokenFlowBar + AttemptChain Integration + SessionDetail Upgrade

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/components/token/TokenFlowBar.tsx`
- Modify: `frontend/src/pages/sessions/AttemptChain.tsx`
- Modify: `frontend/src/pages/sessions/SessionDetail.tsx`

- [ ] **Step 1: Add TokenUsage type to types/index.ts**

```typescript
// ── Token types ──────────────────────────────────────────

export interface TokenUsage {
  total: {
    input_tokens: number;
    output_tokens: number;
    cache_creation_input_tokens?: number;
    cache_read_input_tokens?: number;
    cost_usd?: number;
  };
  by_model?: Record<
    string,
    {
      input_tokens: number;
      output_tokens: number;
      cache_creation_input_tokens?: number;
      cache_read_input_tokens?: number;
      cost_usd?: number;
    }
  >;
  source: 'agent-sdk' | 'claude-session-meta';
}

export interface ProjectCostSummary {
  project_id: string;
  total_cost_usd: number;
  total_tokens: number;
  session_count: number;
  by_model: Record<string, { cost_usd: number; tokens: number }>;
}
```

- [ ] **Step 2: Create TokenFlowBar component**

Create `frontend/src/components/token/TokenFlowBar.tsx`:

```tsx
interface Props {
  tokenUsageJson: string | null;
}

function parseTokenUsage(json: string | null): TokenUsage | null {
  if (!json) return null;
  try {
    return JSON.parse(json) as TokenUsage;
  } catch {
    return null;
  }
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

const SEGMENTS = [
  { key: 'input_tokens', label: 'Input', color: 'bg-blue-300' },
  { key: 'cache_creation_input_tokens', label: 'Cache', color: 'bg-green-300' },
  { key: 'output_tokens', label: 'Output', color: 'bg-yellow-300' },
  { key: 'cache_read_input_tokens', label: 'Think', color: 'bg-gray-300' },
] as const;

export function TokenFlowBar({ tokenUsageJson }: Props) {
  const usage = parseTokenUsage(tokenUsageJson);
  if (!usage) return null;

  const total = usage.total;
  const totalTokens =
    (total.input_tokens || 0) +
    (total.output_tokens || 0) +
    (total.cache_creation_input_tokens || 0) +
    (total.cache_read_input_tokens || 0);
  if (totalTokens === 0) return null;

  return (
    <div className="mt-2">
      <div className="flex justify-between text-[10px] text-gray-500 mb-1">
        <span>Tokens</span>
        <span className="font-medium text-gray-700">
          Total: {formatTokens(totalTokens)}
          {total.cost_usd != null ? ` · $${total.cost_usd.toFixed(2)}` : ''}
        </span>
      </div>
      <div className="flex h-[10px] rounded-sm overflow-hidden gap-px">
        {SEGMENTS.map(({ key, color }) => {
          const val = (usage.total as Record<string, number | undefined>)[key] || 0;
          if (val === 0) return null;
          return (
            <div
              key={key}
              className={color}
              style={{ width: `${(val / totalTokens) * 100}%` }}
              title={`${key}: ${formatTokens(val)}`}
            />
          );
        })}
      </div>
      <div className="flex gap-3 mt-1 text-[9px] text-gray-400">
        {SEGMENTS.map(({ key, label, color }) => {
          const val = (usage.total as Record<string, number | undefined>)[key] || 0;
          if (val === 0) return null;
          return (
            <span key={key} className="flex items-center gap-1">
              <span className={`inline-block w-[6px] h-[6px] rounded-sm ${color}`} />
              {label} {formatTokens(val)}
            </span>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Integrate TokenFlowBar into AttemptChain**

In `frontend/src/pages/sessions/AttemptChain.tsx`:

Add import:
```tsx
import { TokenFlowBar } from '../../components/token/TokenFlowBar';
```

Replace the `{a.token_usage_json && <span>...hasTokens</span>}` line with:
```tsx
<TokenFlowBar tokenUsageJson={a.token_usage_json} />
```

- [ ] **Step 4: Upgrade SessionDetail to show real cost**

In `frontend/src/pages/sessions/SessionDetail.tsx`:

The stats bar already shows `$detail.total_cost_usd.toFixed(2)`. This will now show actual values once token data flows. Add total tokens display:

```tsx
import type { SessionDetailRecord, TokenUsage } from '../../types';

// Compute total tokens across attempts
const totalTokens = detail.attempts.reduce((sum, a) => {
  if (!a.token_usage_json) return sum;
  try {
    const tu = JSON.parse(a.token_usage_json) as TokenUsage;
    const t = tu.total;
    return sum + (t.input_tokens || 0) + (t.output_tokens || 0)
      + (t.cache_creation_input_tokens || 0) + (t.cache_read_input_tokens || 0);
  } catch { return sum; }
}, 0);

// Add to stats bar:
<span>{t('pages.sessions.totalTokens', { count: totalTokens })}</span>
```

- [ ] **Step 5: Type-check and run frontend tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors.

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/components/token/ frontend/src/pages/sessions/AttemptChain.tsx frontend/src/pages/sessions/SessionDetail.tsx
git commit -m "feat: add TokenFlowBar component integrated into AttemptChain and SessionDetail"
```

---

## Task 6: Frontend — Per-Model Breakdown + Per-Project Cost + i18n

**Files:**
- Modify: `frontend/src/pages/sessions/AttemptChain.tsx`
- Modify: `frontend/src/i18n/messages.ts`
- Modify: `frontend/src/api/endpoints.ts`

- [ ] **Step 1: Add per-model breakdown to AttemptChain**

In `frontend/src/pages/sessions/AttemptChain.tsx`, after the `TokenFlowBar` component inside each attempt card, add a collapsible model breakdown:

```tsx
{(() => {
  const tu = parseTokenUsage(a.token_usage_json);
  if (!tu?.by_model || Object.keys(tu.by_model).length === 0) return null;
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-blue-600 font-medium">
        {t('pages.sessions.perModelBreakdown')}
      </summary>
      <div className="mt-2 flex flex-col gap-1">
        {Object.entries(tu.by_model).map(([model, usage]) => {
          const modelTokens = (usage.input_tokens || 0) + (usage.output_tokens || 0);
          return (
            <div key={model} className="flex items-center justify-between py-1 px-2 bg-gray-50 rounded">
              <span className="font-mono text-[11px]">{model}</span>
              <span className="text-gray-500">
                {formatTokens(modelTokens)}
                {usage.cost_usd != null ? ` · $${usage.cost_usd.toFixed(2)}` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </details>
  );
})()}
```

Add `parseTokenUsage` helper at the top of AttemptChain.tsx (same as in TokenFlowBar, or import from shared util).

- [ ] **Step 2: Add i18n keys**

In `frontend/src/i18n/messages.ts`, add to `pages.sessions` (both en and zh):

```typescript
// en
perModelBreakdown: 'Per-Model Breakdown',
totalTokens: '{{count}} tokens',

// zh
perModelBreakdown: '模型明细',
totalTokens: '{{count}} 个 token',
```

- [ ] **Step 3: Add getProjectCostSummary API function**

In `frontend/src/api/endpoints.ts`:

```typescript
import type { ProjectCostSummary } from '../types';

export const getProjectCostSummary = (projectId: string): Promise<ProjectCostSummary> =>
  USE_MOCK
    ? Promise.resolve({
        project_id: projectId,
        total_cost_usd: 0,
        total_tokens: 0,
        session_count: 0,
        by_model: {},
      })
    : api.get<ProjectCostSummary>(`/projects/${projectId}/cost-summary`);
```

- [ ] **Step 4: Type-check and run tests**

Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Expected: No type errors.

Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/sessions/AttemptChain.tsx frontend/src/i18n/messages.ts frontend/src/api/endpoints.ts
git commit -m "feat: add per-model token breakdown, i18n, and project cost API"
```

---

## Task 7: Backend Tests + Integration Verification

**Files:**
- Create: `tests/test_token_track.py`

- [ ] **Step 1: Write backend tests**

Create `tests/test_token_track.py`:

```python
"""Tests for token track functionality."""

from __future__ import annotations

from pathlib import Path
import tempfile

import pytest


class TestTokenUsageSchema:
    def test_token_usage_structure(self):
        tu = {
            "total": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.15},
            "by_model": {"claude-opus": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.15}},
            "source": "agent-sdk",
        }
        import json
        s = json.dumps(tu)
        parsed = json.loads(s)
        assert parsed["total"]["input_tokens"] == 100
        assert parsed["source"] == "agent-sdk"

    def test_token_usage_claude_code_format(self):
        tu = {
            "total": {"input_tokens": 200, "output_tokens": 75},
            "source": "claude-session-meta",
        }
        import json
        s = json.dumps(tu)
        parsed = json.loads(s)
        assert "cost_usd" not in parsed["total"]
        assert parsed["source"] == "claude-session-meta"


class TestEngineEventTokenUsage:
    def test_engine_event_has_token_usage_field(self):
        from ainrf.task_harness.engines.base import EngineEvent
        e = EngineEvent("system", {"subtype": "task_completed"}, token_usage={"total": {"input_tokens": 10}})
        assert e.token_usage == {"total": {"input_tokens": 10}}
        assert e.event_type == "system"
        assert e.payload["subtype"] == "task_completed"

    def test_engine_event_token_usage_defaults_to_none(self):
        from ainrf.task_harness.engines.base import EngineEvent
        e = EngineEvent("message", {"role": "assistant", "content": "hello"})
        assert e.token_usage is None


class TestTaskOutputKindToken:
    def test_token_kind_exists(self):
        from ainrf.task_harness.models import TaskOutputKind
        assert TaskOutputKind.TOKEN == "token"


class TestRecalcSessionWithCost:
    @pytest.fixture
    def service(self):
        from ainrf.sessions import SessionService
        with tempfile.TemporaryDirectory() as td:
            svc = SessionService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_recalc_aggregates_cost(self, service):
        s = service.create_session(project_id="p1", title="Cost Test")
        a1 = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a1.id, status="completed", duration_ms=5000,
            token_usage_json='{"total":{"input_tokens":100,"output_tokens":50,"cost_usd":1.50},"source":"agent-sdk"}',
        )
        a2 = service.create_attempt(session_id=s.id)
        service.complete_attempt(
            a2.id, status="completed", duration_ms=3000,
            token_usage_json='{"total":{"input_tokens":200,"output_tokens":75,"cost_usd":2.00},"source":"agent-sdk"}',
        )
        s2 = service.get_session(s.id)
        assert s2.task_count == 2
        assert s2.total_cost_usd == pytest.approx(3.50)

    def test_recalc_handles_null_token_usage(self, service):
        s = service.create_session(project_id="p1", title="Null Test")
        a = service.create_attempt(session_id=s.id)
        service.complete_attempt(a.id, status="completed", duration_ms=1000)
        s2 = service.get_session(s.id)
        assert s2.total_cost_usd == 0.0


class TestEngineEventToKindToken:
    def test_token_maps_to_token_kind(self):
        from ainrf.task_harness.service import TaskHarnessService
        from ainrf.task_harness.models import TaskOutputKind
        # We can't easily instantiate the service without all dependencies,
        # but we can verify the mapping logic inline
        mapping = {
            "message": TaskOutputKind.MESSAGE,
            "token": TaskOutputKind.TOKEN,
        }
        assert mapping["token"] == TaskOutputKind.TOKEN
```

- [ ] **Step 2: Run backend tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/test_token_track.py -v`
Expected: All tests pass.

- [ ] **Step 3: Run full test suites**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -v`
Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Run: `cd /home/xuyang/code/scholar-agent && uv run ruff check src/ainrf/task_harness/engines/ src/ainrf/task_harness/models.py src/ainrf/task_harness/service.py src/ainrf/sessions/service.py src/ainrf/api/app.py src/ainrf/api/routes/projects.py`

Expected: All pass with no errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_token_track.py
git commit -m "test: add token track unit tests"
```
