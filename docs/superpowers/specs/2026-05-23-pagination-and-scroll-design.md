# Pagination and Scroll Container Redesign

> **Goal:** Fix slow page loads when task/session counts are large, and correct the scroll chain so list components scroll independently within the page shell rather than scrolling the entire `<main>`.

**Architecture:** Cursor-based pagination on backend list endpoints + `useInfiniteQuery` on frontend with IntersectionObserver infinite scroll + scroll container restructuring to isolate overflow to sidebar/content panels and list components.

**Tech Stack:** Python/FastAPI backend (SQLite), React/TypeScript frontend (React Query, Tailwind CSS).

---

## 1. Backend — Cursor-Based Pagination

### 1.1 Tasks Endpoint

`GET /api/tasks`

| Query Param | Type | Default | Description |
|---|---|---|---|
| `project_id` | string | `null` | Filter by project |
| `cursor` | string | `null` | Last task_id from previous page |
| `limit` | int | 50 | Page size (max 200) |
| `include_archived` | bool | false | Include archived tasks |

Response:
```json
{
  "items": [...],
  "total": 142,
  "has_more": true,
  "next_cursor": "task-xyz"
}
```

- `total` only returned on first page (`cursor` is null); omitted on subsequent pages.
- Cursor query: `WHERE (:cursor IS NULL OR task_id > :cursor) ORDER BY task_id ASC LIMIT :limit`

### 1.2 Sessions Endpoint

`GET /api/sessions`

| Query Param | Type | Default | Description |
|---|---|---|---|
| `project_id` | string | `null` | Filter by project |
| `cursor` | string | `null` | Last session_id from previous page |
| `limit` | int | 50 | Page size (max 200) |

Same response shape as tasks. Cursor uses `session_id`.

### 1.3 Sessions Batch Detail (new)

`GET /api/sessions/batch-detail?ids=id1,id2,...`

Returns compact attempt summaries for multiple session IDs in one call, eliminating the N+1 `useQueries` problem on TimelinePage.

### 1.4 Service Layer

- New methods: `list_tasks_cursor(cursor?, limit?, project_id?)`, `list_sessions_cursor(cursor?, limit?, project_id?)`
- Existing non-paginated methods preserved for internal callers with small datasets.
- Batch detail: `get_sessions_batch_detail(ids: list[str])` with a single `SELECT ... FROM attempts WHERE parent_id IN (...)` query.

---

## 2. Frontend — Data Layer

### 2.1 Type Changes

```typescript
export interface TaskListResponse {
  items: TaskSummary[];
  total?: number;       // only on first page
  has_more: boolean;
  next_cursor?: string;
}

export interface SessionListResponse {
  items: SessionRecord[];
  total?: number;
  has_more: boolean;
  next_cursor?: string;
}
```

### 2.2 Endpoint Functions

```typescript
getTasks(params: {
  projectId?: string;
  cursor?: string;
  limit?: number;
  includeArchived?: boolean;
}): Promise<TaskListResponse>

getSessions(params: {
  projectId?: string;
  cursor?: string;
  limit?: number;
}): Promise<SessionListResponse>
```

### 2.3 useInfiniteQuery Migration

Three pages migrate from `useQuery` to `useInfiniteQuery`:

- **ProjectsPage / TasksPage**: `queryKey: ['tasks', projectId]`, `getNextPageParam: (last) => last.has_more ? last.next_cursor : undefined`
- **SessionsPage**: `queryKey: ['sessions', projectId]`, same pattern
- **TimelinePage**: `queryKey: ['timeline-sessions', projectId]`, same pattern

### 2.4 Polling Replacement

Remove fixed-interval polling (`refetchInterval`). Instead:
- Mutation success → `invalidateQueries` triggers first-page refetch.
- User can manually pull-to-refresh or use a refresh button.

### 2.5 TimelinePage N+1 Fix

Replace `useQueries` per-session detail fetching with `GET /api/sessions/batch-detail?ids=...`. Query enabled only when session list data is available. Batch call fetches attempt count, status, and duration for all visible sessions in one request.

---

## 3. Frontend — Scroll Container Restructuring

### 3.1 Root-Level Scroll Lock

`index.css`:
```css
html, body, #root {
  overflow: hidden;
  height: 100%;
}
```

### 3.2 Layout

`Layout.tsx` — `<main>` change `overflow-y-auto` → `overflow-hidden`.

### 3.3 PageShell

`PageShell.tsx` — inner div remove `overflow-auto`. Outer div keeps `flex min-h-0 flex-1` to fill parent.

### 3.4 SplitPane

`SplitPane.tsx`:
- Outer div: remove `overflow-auto`
- Content `<main>` region: add `overflow-y-auto`

The sidebar `<aside>` already has `overflow-y-auto` — keep it.

### 3.5 GanttChart

Add `overflow-y-auto` alongside existing `overflow-x-auto` for vertical scroll.

### 3.6 Resulting Scroll Chain

```
html, body, #root           overflow: hidden
└─ Layout <main>            overflow: hidden
   ├─ [SplitPane pages]
   │  ├─ <aside>            overflow-y-auto  ← sidebar lists
   │  └─ <div> content      overflow-y-auto  ← detail panels
   │
   └─ [Non-SplitPane pages]
      └─ PageShell          fills parent
         └─ GanttChart      overflow-y-auto + overflow-x-auto
```

---

## 4. Infinite Scroll UI

### 4.1 IntersectionObserver Sentinel

A sentinel `<div>` placed at the bottom of list components. When it enters the viewport, `fetchNextPage()` is called.

```tsx
function LoadMoreSentinel({ onVisible, loading }: { onVisible: () => void; loading: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) onVisible();
    }, { root: null, threshold: 0.1 });
    obs.observe(el);
    return () => obs.disconnect();
  }, [onVisible]);
  return <div ref={ref} className="h-8 flex items-center justify-center">
    {loading ? <Spinner /> : null}
  </div>;
}
```

### 4.2 States

- **Loading initial page**: Skeleton or spinner in the list area
- **Loading next page**: Small spinner at the bottom (does not replace existing items)
- **Error**: Toast notification + retry button
- **Empty**: "No tasks" / "No sessions" empty state (existing i18n keys)
- **End of list**: No sentinel, no indicator

---

## 5. Files Modified

| File | Change |
|---|---|
| `src/ainrf/api/routes/tasks.py` | Add `cursor`, `limit` query params; add pagination metadata to response |
| `src/ainrf/api/routes/sessions.py` | Add `cursor`, `limit` query params; add `/batch-detail` endpoint |
| `src/ainrf/task_harness/service.py` | Add `list_tasks_cursor` method |
| `src/ainrf/sessions/service.py` | Add `list_sessions_cursor`, `get_sessions_batch_detail` methods |
| `frontend/src/types/index.ts` | Add `total`, `has_more`, `next_cursor` to list response types |
| `frontend/src/api/endpoints.ts` | Update `getTasks`/`getSessions` signatures; add `getSessionsBatchDetail` |
| `frontend/src/pages/ProjectsPage.tsx` | `useQuery` → `useInfiniteQuery`; add `LoadMoreSentinel` |
| `frontend/src/pages/SessionsPage.tsx` | `useQuery` → `useInfiniteQuery`; add `LoadMoreSentinel` |
| `frontend/src/pages/TimelinePage.tsx` | `useQuery` + `useQueries` → `useInfiniteQuery` + batch detail |
| `frontend/src/components/project/TaskList.tsx` | Add `LoadMoreSentinel`; ensure `min-h-0` for scroll |
| `frontend/src/pages/sessions/SessionList.tsx` | Add `LoadMoreSentinel`; ensure `min-h-0` for scroll |
| `frontend/src/pages/timeline/GanttChart.tsx` | Add `overflow-y-auto` |
| `frontend/src/index.css` | `html, body, #root` → `overflow: hidden; height: 100%` |
| `frontend/src/components/common/Layout.tsx` | `<main>` → `overflow-hidden` |
| `frontend/src/components/layout/PageShell.tsx` | Inner div remove `overflow-auto` |
| `frontend/src/components/layout/SplitPane.tsx` | Outer div remove `overflow-auto`; main area add `overflow-y-auto` |

---

## 6. Verification

1. **Backend tests**: `uv run pytest tests/api/test_tasks.py tests/api/test_sessions.py` — existing tests pass; add cursor pagination test cases
2. **Frontend type check**: `cd frontend && node_modules/.bin/tsc -b`
3. **Frontend tests**: `cd frontend && npm run test:run` — existing tests pass; update any tests that mock list endpoints to include pagination metadata
4. **Manual testing** (with frontend dev server + backend):
   - Create 100+ tasks/sessions, verify pages load in ~50-item batches
   - Scroll to bottom of list, verify next page loads
   - Verify sidebar scrolls independently from detail panel
   - Verify no body-level scrollbar appears
   - Verify non-SplitPane pages (Timeline, Resources) still scroll correctly
   - Verify SplitPane keyboard resize still works
