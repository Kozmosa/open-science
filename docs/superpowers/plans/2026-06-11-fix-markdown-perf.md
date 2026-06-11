# Plan: Fix Task Page Markdown Streaming Performance

## Problem Summary

Task page memory reaches 4000MB+ and CPU 170% when a single message contains formulas.
Root cause: `agent_sdk` engine stores full accumulated text in every streaming delta, causing O(N²) storage.
Frontend amplifies this with no memoization, non-incremental processing, and no component optimization.

## Changes — Grouped by Scope

### Phase 1: Frontend Rendering (no backend changes, safe to ship independently)

**1a. Memoize `SafeMarkdown` parsing** — `frontend/src/pages/tasks/MessageBlocks.tsx`
- Wrap `marked.parse()` in `useMemo` keyed on `content`.
- Stable: pure function of `content`, no side effects.

**1b. Wrap message components in `React.memo`** — `frontend/src/pages/tasks/MessageBlocks.tsx`
- `MessageBlock`, `UserMessage`, `AssistantMessage`, `SystemEventBlock`, `ThinkingBlock`, `ToolCallBlock`, `ToolResultBlock`.
- Each already receives a single `message` prop with stable identity (keyed by `message.id`).
- `React.memo` with custom comparator: re-render only when `message.id` changes OR (message has `blockId` and `content` changed).

**1c. Throttle `writeCache`** — `frontend/src/pages/tasks/useTaskOutputStream.ts`
- Replace per-append `writeCache` call with debounced version (300ms).
- Guarantees at most ~3 serializations/second instead of one per SSE event.
- Flush on unmount / task switch to avoid losing final state.

### Phase 2: Frontend Data Flow (still no backend changes)

**2a. Incremental `convertOutputEventsToMessages`** — `frontend/src/pages/tasks/useTaskMessages.ts`
- Instead of reprocessing ALL `outputItems` on every change, track `lastProcessedSeq`.
- Only convert new events since last processed seq.
- Merge new results into existing `streamMessages` state.
- This reduces work from O(total_events) per update to O(new_events).

**2b. Drop superseded delta events from `outputItems`** — `frontend/src/pages/tasks/useTaskOutputStream.ts`
- After merging, identify events with the same `block_id` in `outputItems`.
- Keep only the latest event per `block_id` (the one with highest `seq`).
- This prunes the quadratic accumulation at the frontend level.
- Must parse event content JSON to extract `block_id` — lightweight since we only check `kind === "message"` or `kind === "thinking"`.
- Events without `block_id` are kept as-is.

### Phase 3: Backend Streaming (the root cause fix)

**3a. Store only delta text in streaming events** — `src/ainrf/harness_engine/engines/agent_sdk.py`
- `_convert_stream_event`: for `content_block_delta`, send only the delta text (not accumulated).
  - `payload["content"] = delta.get("text", "")` instead of `session.stream_block_accumulated`.
  - Keep `block_id` and `is_partial: true`.
  - Keep `session.stream_block_accumulated` for `content_block_stop` (final full content).
- For `content_block_stop`: send the full accumulated text with `is_partial: false` — this is the authoritative final content.
- This changes the per-delta storage from O(accumulated_length) to O(delta_length), i.e. O(N) total instead of O(N²).
- **Frontend compatibility**: the frontend merge logic in `useTaskMessages.ts` already replaces content by `block_id`:
  ```tsx
  result[existingIdx] = { ...result[existingIdx], content: msg.content };
  ```
  With deltas (not accumulated), this would replace the accumulated content with just the delta — **breaking display**.
  So the frontend must be updated simultaneously to **append** delta content instead of replace.

**3b. Frontend delta-append merge** — `frontend/src/pages/tasks/useTaskMessages.ts`
- In the `blockId` merge path: check if `is_partial` is true and payload has delta semantics.
- Strategy: the backend will include an `"is_delta": true` flag in delta events.
  - If `is_delta: true`: `content` is a delta → append to existing message content.
  - If `is_delta` absent/false: `content` is the full text → replace (existing behavior, for `content_block_stop` and non-streaming messages).
- This is backward-compatible: old events (without `is_delta`) use replace semantics.

**3c. Skip superseded partial events on initial load** — `src/ainrf/api/routes/tasks.py`
- For the initial `GET /{task_id}/output` endpoint (used by `loadMore` and initial page load):
  - When fetching historical output, skip `message`/`thinking` events that have `is_partial: true` if a later event with the same `block_id` and `is_partial: false` exists.
  - This reduces initial payload size dramatically for tasks with long streaming history.
  - Implementation: in the SQL query or post-processing, group by parsed `block_id` and keep only the latest event per block (or the final `is_partial: false` event).
  - Simpler alternative: just skip all `is_partial: true` events for completed tasks, since the `content_block_stop` event contains the full text.

## File Change List

| File | Phase | Change |
|------|-------|--------|
| `frontend/src/pages/tasks/MessageBlocks.tsx` | 1a, 1b | `useMemo` on `marked.parse()`; `React.memo` on all block components |
| `frontend/src/pages/tasks/useTaskOutputStream.ts` | 1c, 2b | Debounced `writeCache`; prune superseded events by `block_id` |
| `frontend/src/pages/tasks/useTaskMessages.ts` | 2a, 3b | Incremental event conversion; delta-append merge |
| `src/ainrf/harness_engine/engines/agent_sdk.py` | 3a | Send delta text instead of accumulated text in streaming events |
| `src/ainrf/api/routes/tasks.py` | 3c | Skip superseded partial events on historical fetch |

## Execution Order

Phase 1 → Phase 2 → Phase 3, because:
- Phase 1 is self-contained and provides immediate frontend relief even without backend changes.
- Phase 2 adds frontend-side pruning that works with current backend format.
- Phase 3 fixes the root cause and requires coordinated frontend+backend changes.
- Each phase is independently shippable and improves the situation.

## Backward Compatibility

- Phase 1 & 2: No API changes, purely frontend. Safe.
- Phase 3a: Changes streaming event format. New `is_delta` field.
  - Old frontend (pre-3b) would display only the last delta, not accumulated text → degraded but not broken for existing cached tasks.
  - Old backend + new frontend (3b): `is_delta` absent → falls back to replace semantics → correct.
- Phase 3b: Checks for `is_delta` flag. Falls back to replace if absent.
- Phase 3c: Server-side filtering on read path. No format changes.

## Verification

- After Phase 1: confirm `marked.parse()` only runs when `content` actually changes (React DevTools Profiler).
- After Phase 2: confirm `outputItems` stays bounded for streaming tasks (no quadratic growth).
- After Phase 3: confirm single streaming message of 200K chars stays under 100MB total tab memory.
- All phases: existing `pytest tests/` and `cd frontend && npm run test:run` must pass.
