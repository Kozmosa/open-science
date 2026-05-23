# Pagination and Scroll Container Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add cursor-based pagination to tasks/sessions API, migrate frontend to `useInfiniteQuery` with infinite scroll, and restructure scroll containers so sidebar/content panels scroll independently.

**Architecture:** Backend adds `cursor`+`limit` query params to list endpoints with cursor-based SQL queries. Frontend replaces `useQuery` with `useInfiniteQuery`, uses `IntersectionObserver` sentinels for auto-load, and removes polling in favor of mutation-driven invalidation. CSS/layout changes lock body scroll and isolate overflow to panel-level containers.

**Tech Stack:** Python/FastAPI/SQLite backend, React/TypeScript/React Query/Tailwind CSS frontend.

---

### Task 1: Backend — Add cursor pagination to task list service and schema

**Files:**
- Modify: `src/ainrf/api/schemas.py:555-558`
- Modify: `src/ainrf/task_harness/service.py:587-604, 606-623`

- [ ] **Step 1: Add pagination fields to TaskListResponse schema**

```python
# src/ainrf/api/schemas.py, replace lines 555-558
class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaskSummaryResponse]
    total: int | None = None
    has_more: bool = False
    next_cursor: str | None = None
```

- [ ] **Step 2: Add `list_tasks_cursor` method to task harness service**

In `src/ainrf/task_harness/service.py`, after `list_tasks` (line 604), add:

```python
def list_tasks_cursor(
    self,
    *,
    cursor: str | None = None,
    limit: int = 50,
    include_archived: bool = False,
    owner_user_id: str | None = None,
    project_id: str | None = None,
) -> tuple[list[TaskListItem], int, bool, str | None]:
    self.initialize()
    clauses: list[str] = []
    params: list[str] = []
    if cursor is not None:
        clauses.append("task_id > ?")
        params.append(cursor)
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if owner_user_id is not None:
        clauses.append("owner_user_id = ?")
        params.append(owner_user_id)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with self._connect() as connection:
        count_row = connection.execute(
            f"SELECT COUNT(*) FROM task_harness_tasks {where}",
            tuple(params),
        ).fetchone()
        total = count_row[0] if count_row else 0
        rows = connection.execute(
            f"SELECT * FROM task_harness_tasks {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    items = [self._row_to_list_item(row) for row in rows[:limit]]
    next_cursor = items[-1].task_id if has_more and items else None
    return items, total, has_more, next_cursor
```

- [ ] **Step 3: Run backend tests to verify no regressions**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all existing tests pass (new method is additive, not called yet).

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/api/schemas.py src/ainrf/task_harness/service.py
git commit -m "feat: add cursor pagination to task list service and schema"
```

---

### Task 2: Backend — Update tasks API route for pagination

**Files:**
- Modify: `src/ainrf/api/routes/tasks.py:230-250`
- Modify: `src/ainrf/api/routes/tasks.py:580-603`

- [ ] **Step 1: Update `list_tasks` route handler**

In `src/ainrf/api/routes/tasks.py`, replace lines 230-250:

```python
@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    include_archived: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> TaskListResponse:
    user = request.state.user
    try:
        if user.get("role") == "admin":
            items, total, has_more, next_cursor = service.list_tasks_cursor(
                cursor=cursor,
                limit=limit,
                include_archived=include_archived,
            )
        else:
            items, total, has_more, next_cursor = service.list_tasks_cursor(
                cursor=cursor,
                limit=limit,
                include_archived=include_archived,
                owner_user_id=user["id"],
            )
    except TaskHarnessError as exc:
        raise _translate_task_error(exc) from exc

    return TaskListResponse.model_validate(
        {
            "items": [
                TaskSummaryResponse.model_validate(_serialize_task_summary(item))
                for item in items
            ],
            "total": total if cursor is None else None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )
```

- [ ] **Step 2: Update `list_project_tasks` route handler (lines 580-603)**

Apply the same `cursor`/`limit` params and call `service.list_tasks_cursor(..., project_id=project_id)`.

- [ ] **Step 3: Run backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/api/routes/tasks.py
git commit -m "feat: add cursor pagination to tasks API endpoints"
```

---

### Task 3: Backend — Add cursor pagination to session list service and schema

**Files:**
- Modify: `src/ainrf/api/schemas.py:911-913`
- Modify: `src/ainrf/sessions/service.py:110-134`

- [ ] **Step 1: Add pagination fields to SessionListResponse schema**

```python
# src/ainrf/api/schemas.py, replace lines 911-913
class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list["SessionResponse"]
    total: int | None = None
    has_more: bool = False
    next_cursor: str | None = None
```

- [ ] **Step 2: Add `list_sessions_cursor` method to sessions service**

In `src/ainrf/sessions/service.py`, after line 134, add:

```python
def list_sessions_cursor(
    self,
    *,
    cursor: str | None = None,
    limit: int = 50,
    project_id: str | None = None,
    status: str | None = None,
    owner_user_id: str | None = None,
) -> tuple[list[Session], int, bool, str | None]:
    clauses: list[str] = []
    params: list[str] = []
    if cursor is not None:
        clauses.append("id > ?")
        params.append(cursor)
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if owner_user_id is not None:
        clauses.append("owner_user_id = ?")
        params.append(owner_user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with self._connect() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM task_sessions {where}",
            tuple(params),
        ).fetchone()
        total = count_row[0] if count_row else 0
        rows = conn.execute(
            f"SELECT * FROM task_sessions {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
    has_more = len(rows) > limit
    items = [_row_to_session(r) for r in rows[:limit]]
    next_cursor = items[-1].id if has_more and items else None
    return items, total, has_more, next_cursor
```

Note: The session table's primary key column is `id`, not `session_id`. Verify the column name used in `_row_to_session` (in the existing code at lines 230-240 of service.py, it uses `r["id"]`).

- [ ] **Step 3: Run backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/api/schemas.py src/ainrf/sessions/service.py
git commit -m "feat: add cursor pagination to session list service and schema"
```

---

### Task 4: Backend — Update sessions API route + add batch-detail endpoint

**Files:**
- Modify: `src/ainrf/api/routes/sessions.py:73-94`
- Modify: `src/ainrf/api/routes/sessions.py` (add after existing routes)

- [ ] **Step 1: Update `list_sessions` route handler**

In `src/ainrf/api/routes/sessions.py`, replace lines 73-94:

```python
@router.get("", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> SessionListResponse:
    user = request.state.user
    if user.get("role") == "admin":
        items, total, has_more, next_cursor = service.list_sessions_cursor(
            project_id=project_id,
            status=status,
            cursor=cursor,
            limit=limit,
        )
    else:
        items, total, has_more, next_cursor = service.list_sessions_cursor(
            project_id=project_id,
            status=status,
            cursor=cursor,
            limit=limit,
            owner_user_id=user["id"],
        )
    return SessionListResponse.model_validate(
        {
            "items": [_serialize_session(s) for s in items],
            "total": total if cursor is None else None,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )
```

- [ ] **Step 2: Add `get_sessions_batch_detail` service method**

In `src/ainrf/sessions/service.py`, after `list_attempts_for_sessions` (line 244), add:

```python
def get_sessions_batch_detail(
    self, session_ids: list[str]
) -> dict[str, list[AttemptSummary]]:
    """Return {session_id: [attempt_summaries]} for the given session IDs."""
    if not session_ids:
        return {}
    placeholders = ", ".join(["?"] * len(session_ids))
    with self._connect() as conn:
        rows = conn.execute(
            f"""SELECT parent_id, attempt_seq, status, duration_ms,
                       intervention_reason, created_at
                FROM task_attempts
                WHERE parent_id IN ({placeholders})
                ORDER BY parent_id, attempt_seq ASC""",
            tuple(session_ids),
        ).fetchall()
    result: dict[str, list[dict[str, object]]] = {sid: [] for sid in session_ids}
    for r in rows:
        result[r["parent_id"]].append({
            "attempt_seq": r["attempt_seq"],
            "status": r["status"],
            "duration_ms": r["duration_ms"],
            "intervention_reason": r["intervention_reason"],
            "created_at": r["created_at"],
        })
    return result
```

- [ ] **Step 3: Add batch-detail endpoint to sessions route**

In `src/ainrf/api/routes/sessions.py`, add after existing routes:

```python
@router.get("/batch-detail")
async def get_sessions_batch_detail(
    request: Request,
    ids: str = Query(..., description="Comma-separated session IDs"),
):
    session_ids = [sid.strip() for sid in ids.split(",") if sid.strip()]
    if not session_ids:
        return {"items": {}}
    if len(session_ids) > 200:
        raise HTTPException(status_code=400, detail="Too many IDs (max 200)")
    user = request.state.user
    details = service.get_sessions_batch_detail(session_ids)
    return {"items": details}
```

- [ ] **Step 4: Run backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/api/routes/sessions.py src/ainrf/sessions/service.py
git commit -m "feat: add cursor pagination and batch-detail to sessions API"
```

---

### Task 5: Frontend — Update types and add `getSessionsBatchDetail`

**Files:**
- Modify: `frontend/src/types/index.ts:263-265, 722-724`
- Modify: `frontend/src/api/endpoints.ts:246-249, 266-269, 503-514`
- Modify: `frontend/__tests__/mocks/handlers.ts`

- [ ] **Step 1: Add pagination fields to response types**

In `frontend/src/types/index.ts`, replace lines 263-265:

```typescript
export interface TaskListResponse {
  items: TaskSummary[];
  total?: number;
  has_more: boolean;
  next_cursor?: string | null;
}
```

Replace lines 722-724:

```typescript
export interface SessionListResponse {
  items: SessionRecord[];
  total?: number;
  has_more: boolean;
  next_cursor?: string | null;
}
```

Add a new type after `SessionListResponse`:

```typescript
export interface SessionsBatchDetailResponse {
  items: Record<string, AttemptRecord[]>;
}
```

- [ ] **Step 2: Update endpoint functions with cursor/limit params**

In `frontend/src/api/endpoints.ts`, replace `getTasks` (lines 246-249):

```typescript
export const getTasks = (params: {
  includeArchived?: boolean;
  cursor?: string;
  limit?: number;
} = {}): Promise<TaskListResponse> => {
  const { includeArchived = false, cursor, limit } = params;
  const searchParams = new URLSearchParams();
  searchParams.set('include_archived', String(includeArchived));
  if (cursor) searchParams.set('cursor', cursor);
  if (limit) searchParams.set('limit', String(limit));
  const qs = searchParams.toString();
  return USE_MOCK
    ? Promise.resolve(mockGetTasks())
    : api.get<TaskListResponse>(`/tasks?${qs}`);
};
```

Replace `getProjectTasks` (lines 266-269):

```typescript
export const getProjectTasks = (
  projectId: string,
  params: { includeArchived?: boolean; cursor?: string; limit?: number } = {},
): Promise<TaskListResponse> => {
  const { includeArchived = false, cursor, limit } = params;
  const searchParams = new URLSearchParams();
  searchParams.set('include_archived', String(includeArchived));
  if (cursor) searchParams.set('cursor', cursor);
  if (limit) searchParams.set('limit', String(limit));
  const qs = searchParams.toString();
  return USE_MOCK
    ? Promise.resolve(mockGetProjectTasks())
    : api.get<TaskListResponse>(`/projects/${projectId}/tasks?${qs}`);
};
```

Replace `getSessions` (lines 503-514):

```typescript
export const getSessions = (params: {
  projectId?: string;
  status?: string;
  cursor?: string;
  limit?: number;
} = {}): Promise<SessionListResponse> => {
  const { projectId, status, cursor, limit } = params;
  const searchParams = new URLSearchParams();
  if (projectId) searchParams.set('project_id', projectId);
  if (status) searchParams.set('status', status);
  if (cursor) searchParams.set('cursor', cursor);
  if (limit) searchParams.set('limit', String(limit));
  const qs = searchParams.toString();
  return USE_MOCK
    ? Promise.resolve(mockGetSessions({ projectId, status }))
    : api.get<SessionListResponse>(`/sessions${qs ? `?${qs}` : ''}`);
};
```

Add `getSessionsBatchDetail` after `getSessions`:

```typescript
export const getSessionsBatchDetail = (
  ids: string[],
): Promise<SessionsBatchDetailResponse> => {
  if (ids.length === 0) return Promise.resolve({ items: {} });
  const qs = `ids=${ids.join(',')}`;
  return api.get<SessionsBatchDetailResponse>(`/sessions/batch-detail?${qs}`);
};
```

- [ ] **Step 3: Update MSW handlers to include pagination metadata**

In `frontend/__tests__/mocks/handlers.ts`, update the tasks handler:

```typescript
http.get('/api/projects/default/tasks', () => {
  return HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null });
}),
```

Update the sessions handler:

```typescript
http.get('/api/sessions', () => {
  return HttpResponse.json({ items: [], total: 0, has_more: false, next_cursor: null });
}),
```

Add batch-detail handler:

```typescript
http.get('/api/sessions/batch-detail', () => {
  return HttpResponse.json({ items: {} });
}),
```

- [ ] **Step 4: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b
```

```bash
cd frontend && npm run test:run
```

Expected: type check passes. Existing tests may fail because components still use old function signatures — that will be fixed in Tasks 6-8.

- [ ] **Step 5: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/types/index.ts frontend/src/api/endpoints.ts frontend/__tests__/mocks/handlers.ts
git commit -m "feat: update frontend types and endpoints for cursor pagination"
```

---

### Task 6: Frontend — Create LoadMoreSentinel component

**Files:**
- Create: `frontend/src/components/common/LoadMoreSentinel.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useEffect, useRef } from 'react';

interface Props {
  onVisible: () => void;
  loading: boolean;
}

export default function LoadMoreSentinel({ onVisible, loading }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) onVisible();
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onVisible]);

  return (
    <div ref={ref} className="h-8 flex items-center justify-center">
      {loading && (
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--apple-blue)]" />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run type check**

```bash
cd frontend && node_modules/.bin/tsc -b
```

- [ ] **Step 3: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/components/common/LoadMoreSentinel.tsx
git commit -m "feat: add LoadMoreSentinel component for infinite scroll"
```

---

### Task 7: Frontend — Migrate ProjectsPage to useInfiniteQuery

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx:51-66`
- Modify: `frontend/src/pages/tasks/TaskList.tsx:72-175`

- [ ] **Step 1: Replace useQuery with useInfiniteQuery in ProjectsPage**

In `frontend/src/pages/ProjectsPage.tsx`, replace the import:

```typescript
import { useMutation, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
```

Replace `tasksQuery` (lines 51-56):

```typescript
const tasksQuery = useInfiniteQuery({
  queryKey: ['project-tasks', effectiveProjectId],
  queryFn: ({ pageParam }) =>
    effectiveProjectId
      ? getProjectTasks(effectiveProjectId, { cursor: pageParam, limit: 50 })
      : Promise.resolve({ items: [], total: 0, has_more: false, next_cursor: null }),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
  enabled: effectiveProjectId !== null,
});
```

Replace `tasks` memo (line 65):

```typescript
const tasks = useMemo(
  () => tasksQuery.data?.pages.flatMap((p) => p.items) ?? [],
  [tasksQuery.data],
);
```

Add `hasNextPage` and `isFetchingNextPage` destructuring from `tasksQuery`.

- [ ] **Step 2: Add LoadMoreSentinel to TaskList**

In `frontend/src/pages/tasks/TaskList.tsx`:
- Import `LoadMoreSentinel` from `../../components/common/LoadMoreSentinel`
- Add props: `hasNextPage?: boolean; isFetchingNextPage?: boolean; onLoadMore?: () => void`
- At the bottom of the list `div` (after the last `filteredTasks.map` child), add:

```tsx
{hasNextPage && (
  <LoadMoreSentinel
    onVisible={onLoadMore ?? (() => {})}
    loading={isFetchingNextPage ?? false}
  />
)}
```

- [ ] **Step 3: Wire load-more callbacks in ProjectsPage**

In `ProjectsPage.tsx`, pass to `TaskList`:

```tsx
<TaskList
  tasks={tasks}
  hasNextPage={tasksQuery.hasNextPage}
  isFetchingNextPage={tasksQuery.isFetchingNextPage}
  onLoadMore={() => tasksQuery.fetchNextPage()}
  ...
/>
```

- [ ] **Step 4: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npm run test:run
```

Update any failing test assertions to include new pagination metadata defaults.

- [ ] **Step 5: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/pages/ProjectsPage.tsx frontend/src/pages/tasks/TaskList.tsx
git commit -m "feat: migrate ProjectsPage tasks to useInfiniteQuery with infinite scroll"
```

---

### Task 8: Frontend — Migrate SessionsPage to useInfiniteQuery

**Files:**
- Modify: `frontend/src/pages/SessionsPage.tsx:14-18, 39-61`
- Modify: `frontend/src/pages/sessions/SessionList.tsx:41-69`

- [ ] **Step 1: Replace useQuery with useInfiniteQuery**

In `SessionsPage.tsx`, replace import and sessionsQuery:

```typescript
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';

const sessionsQuery = useInfiniteQuery({
  queryKey: ['sessions'],
  queryFn: ({ pageParam }) => getSessions({ cursor: pageParam, limit: 50 }),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
});
```

Replace `sessions` memo (lines 20-23):

```typescript
const sessions = useMemo(
  () => sessionsQuery.data?.pages.flatMap((p) => p.items) ?? [],
  [sessionsQuery.data],
);
```

- [ ] **Step 2: Add LoadMoreSentinel to SessionList**

In `SessionList.tsx`:
- Import `LoadMoreSentinel`
- Add props: `hasNextPage?: boolean; isFetchingNextPage?: boolean; onLoadMore?: () => void`
- Add `min-h-0` to the outer container for flex shrink:

```tsx
<div className="flex flex-col gap-3 p-2 min-h-0">
```

- After the `</ul>`, add:

```tsx
{hasNextPage && (
  <LoadMoreSentinel
    onVisible={onLoadMore ?? (() => {})}
    loading={isFetchingNextPage ?? false}
  />
)}
```

- [ ] **Step 3: Wire callbacks in SessionsPage**

Pass `hasNextPage`, `isFetchingNextPage`, `onLoadMore` to `SessionList`.

- [ ] **Step 4: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npm run test:run
```

- [ ] **Step 5: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/pages/SessionsPage.tsx frontend/src/pages/sessions/SessionList.tsx
git commit -m "feat: migrate SessionsPage to useInfiniteQuery with infinite scroll"
```

---

### Task 9: Frontend — Migrate TimelinePage to useInfiniteQuery + batch detail

**Files:**
- Modify: `frontend/src/pages/TimelinePage.tsx`

- [ ] **Step 1: Replace sessions useQuery with useInfiniteQuery + remove useQueries**

Remove `refetchInterval: 15000`. Replace `sessionsQuery`:

```typescript
const sessionsQuery = useInfiniteQuery({
  queryKey: ['sessions', projectId],
  queryFn: ({ pageParam }) => getSessions({ projectId: projectId ?? undefined, cursor: pageParam, limit: 50 }),
  initialPageParam: undefined as string | undefined,
  getNextPageParam: (lastPage) => lastPage.has_more ? (lastPage.next_cursor ?? undefined) : undefined,
  refetchInterval: 15000,
});
```

Extract sessions:

```typescript
const sessions = useMemo(
  () => sessionsQuery.data?.pages.flatMap((p) => p.items) ?? [],
  [sessionsQuery.data],
);
```

- [ ] **Step 2: Replace useQueries with single batch-detail query**

Remove `sessionDetails` and `details` memo. Add:

```typescript
const detailQuery = useQuery({
  queryKey: ['session-batch-detail', sessions.map((s) => s.id)],
  queryFn: () => getSessionsBatchDetail(sessions.map((s) => s.id)),
  enabled: sessions.length > 0,
});

const details = useMemo(() => detailQuery.data?.items ?? {}, [detailQuery.data]);
```

Pass `details` as `Record<string, AttemptRecord[]>` to `GanttChart`. Update `GanttChart` props to accept `details` as a `Record<string, AttemptRecord[]>` instead of `SessionDetailRecord[]`.

- [ ] **Step 3: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npm run test:run
```

- [ ] **Step 4: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/pages/TimelinePage.tsx
git commit -m "feat: migrate TimelinePage to useInfiniteQuery with batch detail"
```

---

### Task 10: Frontend — Scroll container restructuring

**Files:**
- Modify: `frontend/src/index.css:102-106`
- Modify: `frontend/src/components/common/Layout.tsx:257-264`
- Modify: `frontend/src/components/layout/PageShell.tsx:11`
- Modify: `frontend/src/components/layout/SplitPane.tsx:69, 93`
- Modify: `frontend/src/pages/timeline/GanttChart.tsx:107`

- [ ] **Step 1: Lock body/root scroll**

In `frontend/src/index.css`, replace lines 102-106:

```css
html,
body,
#root {
  height: 100%;
  overflow: hidden;
}
```

- [ ] **Step 2: Lock Layout <main>**

In `frontend/src/components/common/Layout.tsx`, replace lines 257-264:

```tsx
<main
  className="flex w-full flex-1 flex-col overflow-hidden"
>
  {children}
</main>
```

- [ ] **Step 3: Remove overflow-auto from PageShell inner div**

In `frontend/src/components/layout/PageShell.tsx`, replace line 11:

```tsx
<div className="flex min-h-0 w-full rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
```

- [ ] **Step 4: Fix SplitPane overflow**

In `frontend/src/components/layout/SplitPane.tsx`, line 69 — remove `overflow-auto`:

```tsx
<div className={`flex min-h-0 w-full ${className ?? ''}`}>
```

Line 93 — add `overflow-y-auto`:

```tsx
<main className="flex min-w-0 flex-1 flex-col bg-[var(--bg)] p-4 overflow-y-auto">
```

- [ ] **Step 5: Add vertical scroll to GanttChart**

In `frontend/src/pages/timeline/GanttChart.tsx`, line 107 — add `overflow-y-auto`:

```tsx
<div className="w-full border border-[var(--border)] rounded-lg overflow-x-auto overflow-y-auto">
```

- [ ] **Step 6: Run type check and tests**

```bash
cd frontend && node_modules/.bin/tsc -b && npm run test:run
```

- [ ] **Step 7: Commit**

```bash
cd /home/xuyang/code/scholar-agent && git add frontend/src/index.css frontend/src/components/common/Layout.tsx frontend/src/components/layout/PageShell.tsx frontend/src/components/layout/SplitPane.tsx frontend/src/pages/timeline/GanttChart.tsx
git commit -m "fix: restructure scroll containers — isolate overflow to panels"
```

---

### Task 11: Final verification

- [ ] **Step 1: Backend tests**

```bash
cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q 2>&1 | tail -5
```

Expected: all backend tests pass.

- [ ] **Step 2: Frontend type check**

```bash
cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b
```

Expected: zero type errors.

- [ ] **Step 3: Frontend tests**

```bash
cd /home/xuyang/code/scholar-agent/frontend && npm run test:run
```

Expected: all 28 test files pass, 0 skipped, 0 failed.

- [ ] **Step 4: Manual smoke test checklist**
  - Start backend: `uv run ainrf serve`
  - Start frontend: `cd frontend && npm run dev`
  - Verify ProjectsPage: scroll task list → next page loads; sidebar scrolls independently from canvas
  - Verify SessionsPage: scroll session list → next page loads; sidebar scrolls independently from detail
  - Verify TimelinePage: Gantt chart scrolls vertically
  - Verify no body-level scrollbar appears on any page
  - Verify SplitPane keyboard resize (ArrowLeft/ArrowRight) still works
  - Verify page without SplitPane (Resources, Settings) still scrolls correctly

- [ ] **Step 5: Final commit if any cleanup needed, then push**

```bash
git push
```
