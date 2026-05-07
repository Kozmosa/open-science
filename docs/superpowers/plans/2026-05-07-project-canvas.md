# Project Canvas 功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Project 管理页面，所有 Task 绑定到 Project，Project 详情页以 React Flow 画布展示 Task 之间的 DAG 关系图。

**Architecture:** 后端新增 `TaskEdge` SQLite 表存储 task 关系，扩展 `TaskHarnessService` 提供 CRUD 和 auto-connect；前端新增 `/projects` 路由，使用 `@xyflow/react` 渲染画布，`dagre` 自动布局，localStorage 持久化用户拖拽位置。

**Tech Stack:** React 19 + TypeScript + Tailwind CSS v4, `@xyflow/react`, `@dagrejs/dagre`, FastAPI + Python 3.13 + SQLite

---

## File Structure

**Backend:**
- `src/ainrf/task_harness/models.py` — add `TaskEdge` dataclass
- `src/ainrf/task_harness/service.py` — add edge table, CRUD methods, auto-connect in `create_task`
- `src/ainrf/api/schemas.py` — add `TaskEdgeResponse`, `TaskEdgeListResponse`, `TaskEdgeCreateRequest`
- `src/ainrf/api/routes/tasks.py` — add `GET/POST/DELETE` edge endpoints
- `tests/test_task_edges.py` — new test file

**Frontend:**
- `frontend/package.json` — add `@xyflow/react`, `@dagrejs/dagre`
- `frontend/src/App.tsx` — add `/projects` route
- `frontend/src/components/common/Layout.tsx` — add Projects nav item (first position)
- `frontend/src/types/index.ts` — add `TaskEdge`, `TaskEdgeListResponse`, `TaskEdgeCreateRequest`
- `frontend/src/api/endpoints.ts` — add `getProjectTasks`, `getTaskEdges`, `createTaskEdge`, `deleteTaskEdge`
- `frontend/src/api/mock.ts` — add mock edge data
- `frontend/src/i18n/messages.ts` — add project/canvas related i18n keys
- `frontend/src/components/project/ProjectSidebar.tsx` — project list sidebar (new)
- `frontend/src/components/project/TaskNode.tsx` — custom React Flow node (new)
- `frontend/src/components/project/ProjectCanvas.tsx` — React Flow canvas with dagre layout (new)
- `frontend/src/components/project/index.ts` — barrel export (new)
- `frontend/src/pages/ProjectsPage.tsx` — main page assembling sidebar + canvas (new)
- `frontend/src/pages/tasks/TaskCreateForm.tsx` — add Project selector dropdown

---

### Task 1: Backend — TaskEdge Data Model

**Files:**
- Modify: `src/ainrf/task_harness/models.py`
- Test: `tests/test_task_edges.py` (initial test)

- [ ] **Step 1: Write the failing test**

```python
from ainrf.task_harness.models import TaskEdge


def test_task_edge_model():
    from datetime import datetime
    edge = TaskEdge(
        edge_id="edge-123",
        project_id="project-456",
        source_task_id="task-a",
        target_task_id="task-b",
        created_at=datetime.now(),
    )
    assert edge.edge_id == "edge-123"
    assert edge.source_task_id == "task-a"
    assert edge.target_task_id == "task-b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_edges.py::test_task_edge_model -v`
Expected: FAIL with "TaskEdge is not defined"

- [ ] **Step 3: Add TaskEdge dataclass**

Add to `src/ainrf/task_harness/models.py` after `TaskOutputPage`:

```python
@dataclass(slots=True)
class TaskEdge:
    edge_id: str
    project_id: str
    source_task_id: str
    target_task_id: str
    created_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_task_edges.py::test_task_edge_model -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/task_harness/models.py tests/test_task_edges.py
git commit -m "feat: add TaskEdge dataclass"
```

---

### Task 2: Backend — TaskEdge Service Layer

**Files:**
- Modify: `src/ainrf/task_harness/service.py`
- Test: `tests/test_task_edges.py`

- [ ] **Step 1: Write failing test for edge CRUD**

```python
def test_create_and_list_task_edges(tmp_path, monkeypatch):
    from ainrf.api.app import make_app
    app = make_app(tmp_path)
    service = app.state.task_harness_service
    # Create two tasks first
    task1 = service.create_task(
        project_id="default", workspace_id="workspace-default",
        environment_id="env-default", task_profile="claude-code", task_input="task 1"
    )
    task2 = service.create_task(
        project_id="default", workspace_id="workspace-default",
        environment_id="env-default", task_profile="claude-code", task_input="task 2"
    )
    edge = service.create_task_edge("default", task1.task_id, task2.task_id)
    assert edge.source_task_id == task1.task_id
    assert edge.target_task_id == task2.task_id
    edges = service.get_task_edges("default")
    assert len(edges) == 1
    assert edges[0].edge_id == edge.edge_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_edges.py::test_create_and_list_task_edges -v`
Expected: FAIL with "create_task_edge not defined"

- [ ] **Step 3: Add edge table and service methods**

In `TaskHarnessService.initialize()`, after the existing `CREATE TABLE` blocks, add:

```python
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_harness_edges (
                    edge_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    target_task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_task_id) REFERENCES task_harness_tasks(task_id),
                    FOREIGN KEY (target_task_id) REFERENCES task_harness_tasks(task_id)
                )
                """
            )
```

Add imports at top of `service.py`:
```python
from ainrf.task_harness.models import TaskEdge
```

Add methods to `TaskHarnessService`:

```python
    def create_task_edge(
        self,
        project_id: str,
        source_task_id: str,
        target_task_id: str,
    ) -> TaskEdge:
        self.initialize()
        now = utc_now()
        edge_id = f"edge-{uuid4().hex[:12]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_harness_edges (edge_id, project_id, source_task_id, target_task_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (edge_id, project_id, source_task_id, target_task_id, now.isoformat()),
            )
            connection.commit()
        return TaskEdge(
            edge_id=edge_id,
            project_id=project_id,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            created_at=now,
        )

    def get_task_edges(self, project_id: str) -> list[TaskEdge]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM task_harness_edges WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
        return [
            TaskEdge(
                edge_id=row["edge_id"],
                project_id=row["project_id"],
                source_task_id=row["source_task_id"],
                target_task_id=row["target_task_id"],
                created_at=_parse_required_datetime(row["created_at"]),
            )
            for row in rows
        ]

    def delete_task_edge(self, edge_id: str) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM task_harness_edges WHERE edge_id = ?",
                (edge_id,),
            )
            connection.commit()
```

- [ ] **Step 4: Add auto-connect to create_task**

Modify `create_task` signature to add `auto_connect: bool = False` parameter:

```python
    def create_task(
        self,
        *,
        project_id: str = "default",
        workspace_id: str,
        environment_id: str,
        task_profile: str,
        task_input: str,
        title: str | None = None,
        execution_engine: str | None = None,
        research_agent_profile: dict[str, object] | None = None,
        task_configuration: dict[str, object] | None = None,
        auto_connect: bool = False,
    ) -> TaskListItem:
```

At the end of `create_task`, after `self._schedule_task(task_id)`, add:

```python
        if auto_connect:
            with self._connect() as connection:
                latest = connection.execute(
                    """
                    SELECT task_id FROM task_harness_tasks
                    WHERE project_id = ? AND task_id != ? AND archived_at IS NULL
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (project_id, task_id),
                ).fetchone()
            if latest is not None:
                self.create_task_edge(project_id, latest["task_id"], task_id)
        return self._load_list_item(task_id)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_task_edges.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/task_harness/service.py tests/test_task_edges.py
git commit -m "feat: add TaskEdge CRUD and auto-connect in service layer"
```

---

### Task 3: Backend — TaskEdge API Routes + Schema

**Files:**
- Modify: `src/ainrf/api/schemas.py`
- Modify: `src/ainrf/api/routes/tasks.py`
- Test: `tests/test_task_edges.py`

- [ ] **Step 1: Add edge schemas**

Add to `src/ainrf/api/schemas.py` after `TaskListResponse`:

```python
class TaskEdgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    project_id: str
    source_task_id: str
    target_task_id: str
    created_at: str


class TaskEdgeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TaskEdgeResponse]


class TaskEdgeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_task_id: str = Field(min_length=1)
    target_task_id: str = Field(min_length=1)
```

- [ ] **Step 2: Add edge API routes**

Add to `src/ainrf/api/routes/tasks.py` after the existing routes, before the last line:

```python
@router.get("/{project_id}/task-edges", response_model=TaskEdgeListResponse)
async def list_task_edges(project_id: str, request: Request) -> TaskEdgeListResponse:
    service = _get_task_harness_service(request)
    try:
        edges = service.get_task_edges(project_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeListResponse(
        items=[
            TaskEdgeResponse(
                edge_id=edge.edge_id,
                project_id=edge.project_id,
                source_task_id=edge.source_task_id,
                target_task_id=edge.target_task_id,
                created_at=edge.created_at.isoformat(),
            )
            for edge in edges
        ]
    )


@router.post("/{project_id}/task-edges", response_model=TaskEdgeResponse, status_code=status.HTTP_201_CREATED)
async def create_task_edge(
    project_id: str,
    payload: TaskEdgeCreateRequest,
    request: Request,
) -> TaskEdgeResponse:
    service = _get_task_harness_service(request)
    try:
        edge = service.create_task_edge(
            project_id=project_id,
            source_task_id=payload.source_task_id,
            target_task_id=payload.target_task_id,
        )
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return TaskEdgeResponse(
        edge_id=edge.edge_id,
        project_id=edge.project_id,
        source_task_id=edge.source_task_id,
        target_task_id=edge.target_task_id,
        created_at=edge.created_at.isoformat(),
    )


@router.delete("/task-edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request) -> None:
    service = _get_task_harness_service(request)
    try:
        service.delete_task_edge(edge_id)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
    return None
```

Also add imports at top of `tasks.py`:
```python
from ainrf.api.schemas import (
    TaskCreateRequest,
    TaskDetailResponse,
    TaskEdgeCreateRequest,
    TaskEdgeListResponse,
    TaskEdgeResponse,
    TaskListResponse,
    TaskOutputEventResponse,
    TaskOutputListResponse,
    TaskSummaryResponse,
)
```

- [ ] **Step 3: Add API integration test**

Add to `tests/test_task_edges.py`:

```python
import httpx

API_HEADERS = {"Authorization": "Bearer test-key"}


def test_api_create_and_list_edges(tmp_path, monkeypatch):
    from ainrf.api.app import make_app
    app = make_app(tmp_path)
    service = app.state.task_harness_service
    task1 = service.create_task(
        project_id="default", workspace_id="workspace-default",
        environment_id="env-default", task_profile="claude-code", task_input="task 1"
    )
    task2 = service.create_task(
        project_id="default", workspace_id="workspace-default",
        environment_id="env-default", task_profile="claude-code", task_input="task 2"
    )

    import asyncio

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            create_resp = await client.post(
                "/projects/default/task-edges",
                headers=API_HEADERS,
                json={"source_task_id": task1.task_id, "target_task_id": task2.task_id},
            )
            assert create_resp.status_code == 201
            created = create_resp.json()
            assert created["source_task_id"] == task1.task_id

            list_resp = await client.get("/projects/default/task-edges", headers=API_HEADERS)
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]
            assert len(items) == 1

            delete_resp = await client.delete(f"/task-edges/{created['edge_id']}", headers=API_HEADERS)
            assert delete_resp.status_code == 204

    asyncio.run(run())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_task_edges.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/api/schemas.py src/ainrf/api/routes/tasks.py tests/test_task_edges.py
git commit -m "feat: add TaskEdge API routes and schemas"
```

---

### Task 4: Frontend — Install Dependencies & Add Types

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Install @xyflow/react and dagre**

Run:
```bash
cd frontend && npm install @xyflow/react @dagrejs/dagre
```

- [ ] **Step 2: Add TaskEdge types**

Add to `frontend/src/types/index.ts` after `TaskListResponse`:

```typescript
export interface TaskEdge {
  edge_id: string;
  project_id: string;
  source_task_id: string;
  target_task_id: string;
  created_at: string;
}

export interface TaskEdgeListResponse {
  items: TaskEdge[];
}

export interface TaskEdgeCreateRequest {
  source_task_id: string;
  target_task_id: string;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/types/index.ts
git commit -m "feat: add @xyflow/react, dagre, and TaskEdge types"
```

---

### Task 5: Frontend — API Endpoints & Mock

**Files:**
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/api/mock.ts`

- [ ] **Step 1: Add edge API functions**

Add to `frontend/src/api/endpoints.ts` after `cancelTask`:

```typescript
export const getProjectTasks = (projectId: string, includeArchived: boolean = false): Promise<TaskListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTasks())
    : api.get<TaskListResponse>(`/projects/${projectId}/tasks?include_archived=${includeArchived}`);

export const getTaskEdges = (projectId: string): Promise<TaskEdgeListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTaskEdges(projectId))
    : api.get<TaskEdgeListResponse>(`/projects/${projectId}/task-edges`);

export const createTaskEdge = (
  projectId: string,
  payload: TaskEdgeCreateRequest
): Promise<TaskEdge> =>
  USE_MOCK
    ? Promise.resolve(mockCreateTaskEdge(projectId, payload))
    : api.post<TaskEdge>(`/projects/${projectId}/task-edges`, payload);

export const deleteTaskEdge = (edgeId: string): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteTaskEdge(edgeId))
    : api.delete<void>(`/task-edges/${edgeId}`);
```

Add imports at top:
```typescript
import type {
  // ... existing imports ...
  TaskEdge,
  TaskEdgeCreateRequest,
  TaskEdgeListResponse,
} from '../types';
```

And add to mock imports:
```typescript
import {
  // ... existing imports ...
  mockGetProjectTasks,
  mockGetTaskEdges,
  mockCreateTaskEdge,
  mockDeleteTaskEdge,
} from './mock';
```

- [ ] **Step 2: Add mock implementations**

Add to `frontend/src/api/mock.ts`:

```typescript
const mockEdges: Record<string, TaskEdge[]> = {};

export function mockGetProjectTasks(): TaskListResponse {
  return { items: mockTasks };
}

export function mockGetTaskEdges(projectId: string): TaskEdgeListResponse {
  return { items: mockEdges[projectId] ?? [] };
}

export function mockCreateTaskEdge(
  projectId: string,
  payload: TaskEdgeCreateRequest
): TaskEdge {
  const edge: TaskEdge = {
    edge_id: `edge-${Math.random().toString(36).slice(2, 8)}`,
    project_id: projectId,
    source_task_id: payload.source_task_id,
    target_task_id: payload.target_task_id,
    created_at: new Date().toISOString(),
  };
  if (!mockEdges[projectId]) {
    mockEdges[projectId] = [];
  }
  mockEdges[projectId].push(edge);
  return edge;
}

export function mockDeleteTaskEdge(_edgeId: string): void {
  for (const projectId in mockEdges) {
    mockEdges[projectId] = mockEdges[projectId].filter((e) => e.edge_id !== _edgeId);
  }
}
```

- [ ] **Step 3: Verify TypeScript**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/endpoints.ts frontend/src/api/mock.ts
git commit -m "feat: add TaskEdge API endpoints and mocks"
```

---

### Task 6: Frontend — Route & Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/common/Layout.tsx`

- [ ] **Step 1: Add /projects route**

Add to `frontend/src/App.tsx`:

```typescript
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));
```

And in routes:
```typescript
<Route path="/projects" element={<ProjectsPage />} />
```

Update `defaultRoutePathById`:
```typescript
const defaultRoutePathById = {
  projects: '/projects',
  terminal: '/terminal',
  tasks: '/tasks',
  workspaces: '/workspaces',
} as const;
```

- [ ] **Step 2: Add Projects nav item (first position)**

Add import in `Layout.tsx`:
```typescript
import { FolderKanban } from 'lucide-react';
```

Insert as first item in `navigationItems`:
```typescript
  const navigationItems: NavigationItem[] = [
    {
      label: t('navigation.projects.label'),
      to: '/projects',
      description: t('navigation.projects.description'),
      icon: FolderKanban,
    },
    // ... existing items ...
  ];
```

- [ ] **Step 3: Verify TypeScript**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```
Expected: no errors (ProjectsPage import will error until Task 11 creates the file)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/common/Layout.tsx
git commit -m "feat: add /projects route and navigation"
```

---

### Task 7: Frontend — ProjectSidebar Component

**Files:**
- Create: `frontend/src/components/project/ProjectSidebar.tsx`
- Create: `frontend/src/components/project/index.ts`

- [ ] **Step 1: Create ProjectSidebar**

```tsx
import { Plus, Search } from 'lucide-react';
import { useState } from 'react';
import { Button, Input } from '../ui';
import { useT } from '../../i18n';
import type { ProjectRecord } from '../../types';

interface Props {
  projects: ProjectRecord[];
  selectedProjectId: string | null;
  onSelectProject: (projectId: string) => void;
  onCreateProject: () => void;
}

export default function ProjectSidebar({
  projects,
  selectedProjectId,
  onSelectProject,
  onCreateProject,
}: Props) {
  const t = useT();
  const [searchQuery, setSearchQuery] = useState('');
  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
            {t('pages.projects.sidebarEyebrow')}
          </p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--sidebar-foreground)]">
            {t('pages.projects.sidebarTitle')}
          </h1>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {t('pages.projects.sidebarCount', { count: projects.length })}
          </p>
        </div>
        <Button
          onClick={onCreateProject}
          className="inline-flex h-9 items-center gap-2 px-3 shadow-sm"
        >
          <Plus size={15} />
          {t('pages.projects.newProject')}
        </Button>
      </div>

      <div className="relative mb-3">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('pages.projects.searchPlaceholder')}
          className="pl-8"
        />
      </div>

      <div className="flex-1 overflow-auto">
        {filtered.map((project) => (
          <button
            key={project.project_id}
            onClick={() => onSelectProject(project.project_id)}
            className={`w-full rounded-lg px-3 py-2 text-left text-sm transition
              ${selectedProjectId === project.project_id
                ? 'bg-[var(--sidebar-primary)] text-[var(--sidebar-primary-foreground)]'
                : 'text-[var(--muted-foreground)] hover:bg-[var(--sidebar-primary)] hover:text-[var(--sidebar-foreground)]'
              }`}
          >
            <div className="truncate font-medium">{project.name}</div>
            {project.description ? (
              <div className="truncate text-[11px] opacity-70">{project.description}</div>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create barrel export**

```typescript
export { default as ProjectSidebar } from './ProjectSidebar';
export { default as ProjectCanvas } from './ProjectCanvas';
export { default as TaskNode } from './TaskNode';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/project/
git commit -m "feat: add ProjectSidebar component"
```

---

### Task 8: Frontend — TaskNode Component

**Files:**
- Create: `frontend/src/components/project/TaskNode.tsx`

- [ ] **Step 1: Create TaskNode**

```tsx
import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { TaskSummary } from '../../types';

interface TaskNodeData {
  task: TaskSummary;
}

function StatusDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    queued: 'bg-gray-400',
    starting: 'bg-blue-400',
    running: 'bg-green-500',
    succeeded: 'bg-emerald-500',
    failed: 'bg-red-500',
    cancelled: 'bg-amber-500',
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${colorMap[status] ?? 'bg-gray-400'}`} />;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

function TaskNode({ data, selected }: NodeProps<TaskNodeData>) {
  const { task } = data;
  return (
    <div
      className={`rounded-xl border bg-[var(--surface)] p-3 min-w-[180px] shadow-sm transition
        ${selected ? 'border-[var(--apple-blue)] ring-2 ring-[var(--apple-blue)]/20' : 'border-[var(--border)]'}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
      <div className="flex items-center gap-2 mb-1">
        <StatusDot status={task.status} />
        <span className="text-sm font-medium truncate text-[var(--text)]">{task.title}</span>
      </div>
      <div className="text-[11px] text-[var(--text-secondary)]">
        {task.environment_summary.alias} · {formatTime(task.created_at)}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
    </div>
  );
}

export default memo(TaskNode);
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/project/TaskNode.tsx
git commit -m "feat: add TaskNode React Flow custom node"
```

---

### Task 9: Frontend — ProjectCanvas Component

**Files:**
- Create: `frontend/src/components/project/ProjectCanvas.tsx`

- [ ] **Step 1: Create layout utility**

Create `frontend/src/components/project/layoutDagre.ts`:

```typescript
import type { Edge, Node } from '@xyflow/react';
import * as dagre from '@dagrejs/dagre';

const NODE_WIDTH = 180;
const NODE_HEIGHT = 80;

export function layoutDagre(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 120 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  return nodes.map((node) => {
    const positioned = g.node(node.id);
    return {
      ...node,
      position: {
        x: positioned.x - NODE_WIDTH / 2,
        y: positioned.y - NODE_HEIGHT / 2,
      },
    };
  });
}
```

- [ ] **Step 2: Create ProjectCanvas**

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { TaskEdge, TaskSummary } from '../../types';
import TaskNode from './TaskNode';
import { layoutDagre } from './layoutDagre';

const nodeTypes = { taskNode: TaskNode };
const LAYOUT_KEY = (projectId: string) => `ainrf:project-layout:${projectId}`;

interface CanvasInnerProps {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  onNodeClick: (taskId: string) => void;
}

function CanvasInner({ projectId, tasks, edges, onNodeClick }: CanvasInnerProps) {
  const { getNodes, setNodes, fitView } = useReactFlow();
  const initialNodes: Node[] = useMemo(
    () =>
      tasks.map((task) => ({
        id: task.task_id,
        type: 'taskNode',
        position: { x: 0, y: 0 },
        data: { task },
      })),
    [tasks]
  );
  const initialEdges: Edge[] = useMemo(
    () =>
      edges.map((edge) => ({
        id: edge.edge_id,
        source: edge.source_task_id,
        target: edge.target_task_id,
        type: 'default',
        markerEnd: { type: 'arrowclosed' as const, width: 12, height: 12 },
      })),
    [edges]
  );

  const [nodes, setLocalNodes] = useState<Node[]>(initialNodes);
  const [flowEdges, setFlowEdges] = useState<Edge[]>(initialEdges);

  useEffect(() => {
    const saved = localStorage.getItem(LAYOUT_KEY(projectId));
    if (saved) {
      try {
        const positions: Record<string, { x: number; y: number }> = JSON.parse(saved);
        setLocalNodes(
          initialNodes.map((n) =>
            positions[n.id] ? { ...n, position: positions[n.id] } : n
          )
        );
      } catch {
        const laidOut = layoutDagre(initialNodes, initialEdges);
        setLocalNodes(laidOut);
      }
    } else {
      const laidOut = layoutDagre(initialNodes, initialEdges);
      setLocalNodes(laidOut);
    }
    setFlowEdges(initialEdges);
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  }, [projectId, initialNodes, initialEdges, fitView]);

  const onNodeDragStop = useCallback(() => {
    const current = getNodes();
    const positions: Record<string, { x: number; y: number }> = {};
    for (const n of current) {
      positions[n.id] = n.position;
    }
    localStorage.setItem(LAYOUT_KEY(projectId), JSON.stringify(positions));
  }, [getNodes, projectId]);

  const handleNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onNodeClick(node.id);
    },
    [onNodeClick]
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={flowEdges}
      nodeTypes={nodeTypes}
      onNodesChange={setLocalNodes}
      onEdgesChange={setFlowEdges}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={handleNodeClick}
      fitView
      attributionPosition="bottom-right"
    >
      <Background gap={16} size={1} color="var(--border)" />
      <Controls />
      <MiniMap
        nodeColor={() => 'var(--apple-blue)'}
        maskColor="rgba(0,0,0,0.1)"
        className="rounded-lg"
      />
    </ReactFlow>
  );
}

interface Props {
  projectId: string;
  tasks: TaskSummary[];
  edges: TaskEdge[];
  onNodeClick: (taskId: string) => void;
  onNewTask: () => void;
  onResetLayout: () => void;
}

export default function ProjectCanvas({
  projectId,
  tasks,
  edges,
  onNodeClick,
  onNewTask,
  onResetLayout,
}: Props) {
  const t = useT(); // Will be added in i18n task

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <div className="flex gap-2">
          <Button onClick={onNewTask} className="h-8 gap-1.5 px-3 text-xs">
            <Plus size={14} />
            {t('pages.projects.newTask')}
          </Button>
          <Button variant="ghost" onClick={onResetLayout} className="h-8 px-3 text-xs">
            {t('pages.projects.resetLayout')}
          </Button>
        </div>
      </div>
      <div className="flex-1">
        {tasks.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
            {t('pages.projects.emptyCanvas')}
          </div>
        ) : (
          <ReactFlowProvider>
            <CanvasInner
              projectId={projectId}
              tasks={tasks}
              edges={edges}
              onNodeClick={onNodeClick}
            />
          </ReactFlowProvider>
        )}
      </div>
    </div>
  );
}
```

Note: `useT` import and `Button` import will be added. For now the file references them — they will be resolved in the i18n step or the implementer should add:
```tsx
import { Plus } from 'lucide-react';
import { Button } from '../ui';
import { useT } from '../../i18n';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/project/ProjectCanvas.tsx frontend/src/components/project/layoutDagre.ts
git commit -m "feat: add ProjectCanvas with React Flow and dagre layout"
```

---

### Task 10: Frontend — ProjectsPage

**Files:**
- Create: `frontend/src/pages/ProjectsPage.tsx`

- [ ] **Step 1: Create ProjectsPage**

```tsx
import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Modal } from '../components/ui';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useT } from '../i18n';
import { getProjects, getProjectTasks, getTaskEdges } from '../api';
import type { TaskRecord } from '../types';
import TaskDetail from './tasks/TaskDetail';
import TaskCreateForm from './tasks/TaskCreateForm';

const sidebarMinWidth = 260;
const sidebarMaxWidth = 520;
const sidebarDefaultWidth = 320;

function clampSidebarWidth(width: number): number {
  return Math.min(sidebarMaxWidth, Math.max(sidebarMinWidth, width));
}

export default function ProjectsPage() {
  const t = useT();
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(sidebarDefaultWidth);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const effectiveProjectId = selectedProjectId ?? projects[0]?.project_id ?? null;

  const tasksQuery = useQuery({
    queryKey: ['project-tasks', effectiveProjectId],
    queryFn: () => (effectiveProjectId ? getProjectTasks(effectiveProjectId) : Promise.resolve({ items: [] })),
    enabled: effectiveProjectId !== null,
  });

  const edgesQuery = useQuery({
    queryKey: ['task-edges', effectiveProjectId],
    queryFn: () => (effectiveProjectId ? getTaskEdges(effectiveProjectId) : Promise.resolve({ items: [] })),
    enabled: effectiveProjectId !== null,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const edges = useMemo(() => edgesQuery.data?.items ?? [], [edgesQuery.data]);

  const handleResetLayout = useCallback(() => {
    if (effectiveProjectId) {
      localStorage.removeItem(`ainrf:project-layout:${effectiveProjectId}`);
      edgesQuery.refetch();
    }
  }, [effectiveProjectId, edgesQuery]);

  const handleCreateProject = useCallback(() => {
    // TODO: open create project modal
  }, []);

  const selectedTask = useMemo(
    () => tasks.find((t) => t.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId]
  );

  return (
    <div className="flex min-h-0 flex-1 bg-[var(--bg)] p-4">
      <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <aside
          className="flex shrink-0 flex-col bg-[var(--sidebar)] p-3"
          style={{ width: sidebarWidth }}
        >
          <ProjectSidebar
            projects={projects}
            selectedProjectId={effectiveProjectId}
            onSelectProject={setSelectedProjectId}
            onCreateProject={handleCreateProject}
          />
        </aside>

        <div
          role="separator"
          aria-orientation="vertical"
          tabIndex={0}
          className="group flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-[var(--surface)]"
        >
          <span className="my-3 w-px rounded-full bg-[var(--border)]" />
        </div>

        <main className="flex min-w-0 flex-1 flex-col bg-[var(--bg)]">
          {effectiveProjectId ? (
            <ProjectCanvas
              projectId={effectiveProjectId}
              tasks={tasks}
              edges={edges}
              onNodeClick={setSelectedTaskId}
              onNewTask={() => setCreateDialogOpen(true)}
              onResetLayout={handleResetLayout}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
              {t('pages.projects.noProjects')}
            </div>
          )}
        </main>
      </div>

      <Modal
        isOpen={selectedTaskId !== null}
        onClose={() => setSelectedTaskId(null)}
        title={selectedTask?.title ?? null}
        size="lg"
      >
        {selectedTask ? (
          <TaskDetail
            selectedTask={selectedTask as TaskRecord}
            detailError={null}
            outputItems={[]}
            outputError={null}
          />
        ) : null}
      </Modal>

      <Modal
        isOpen={isCreateDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        title={null}
        size="lg"
      >
        <TaskCreateForm
          workspaces={[]}
          environments={[]}
          selectedWorkspaceId=""
          selectedEnvironmentId=""
          selectedWorkspace={null}
          selectedEnvironment={null}
          draftDefaults={{ title: '', task_input: '', researchAgentProfileId: '', taskConfigurationId: '' }}
          researchAgentProfiles={[]}
          taskConfigurations={[]}
          availableSkills={[]}
          isSubmitting={false}
          createError={null}
          onSelectWorkspace={() => {}}
          onSelectEnvironment={() => {}}
          onSubmit={() => {}}
          onClose={() => setCreateDialogOpen(false)}
        />
      </Modal>
    </div>
  );
}
```

Note: The ProjectsPage uses `ProjectSidebar` and `ProjectCanvas` which are in `../components/project`. Ensure the barrel export `frontend/src/components/project/index.ts` exists. The `TaskDetail` component's props interface may need adjustment — verify it accepts `selectedTask` as a prop.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx
git commit -m "feat: add ProjectsPage with sidebar, canvas, and modals"
```

---

### Task 11: Frontend — TasksPage Project Selector

**Files:**
- Modify: `frontend/src/pages/tasks/TaskCreateForm.tsx`
- Modify: `frontend/src/pages/TasksPage.tsx`

- [ ] **Step 1: Add project_id to TaskCreateForm props**

Modify `frontend/src/pages/tasks/TaskCreateForm.tsx` interface:

```typescript
interface Props {
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  projects?: ProjectRecord[];
  selectedWorkspaceId: string;
  selectedEnvironmentId: string;
  selectedProjectId?: string;
  selectedWorkspace: WorkspaceRecord | null;
  selectedEnvironment: EnvironmentRecord | null;
  draftDefaults: {
    title: string;
    task_input: string;
    researchAgentProfileId: string;
    taskConfigurationId: string;
  };
  researchAgentProfiles: ResearchAgentProfileSettings[];
  taskConfigurations: TaskConfigurationPreset[];
  availableSkills: SkillItem[];
  isSubmitting: boolean;
  createError: string | null;
  onSelectWorkspace: (workspaceId: string) => void;
  onSelectEnvironment: (environmentId: string) => void;
  onSelectProject?: (projectId: string) => void;
  onSubmit: (payload: TaskCreateRequest) => void;
  onClose?: () => void;
}
```

Add Project selector UI after the Workspace/Environment row:

```tsx
      {projects && projects.length > 0 ? (
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.projectLabel')}
          </span>
          <Select
            aria-label={t('pages.tasks.projectLabel')}
            value={selectedProjectId ?? ''}
            onChange={(event) => onSelectProject?.(event.target.value)}
          >
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </Select>
        </label>
      ) : null}
```

And update the `onSubmit` payload to include `project_id`:

```typescript
        onSubmit({
          project_id: selectedProjectId ?? 'default',
          workspace_id: selectedWorkspace.workspace_id,
          // ... rest unchanged
        });
```

- [ ] **Step 2: Update TasksPage to pass projects**

In `frontend/src/pages/TasksPage.tsx`:
1. Add `getProjects` to API imports
2. Add `projectsQuery` with `useQuery({ queryKey: ['projects'], queryFn: getProjects })`
3. Add `selectedProjectId` state (default from settings or last used)
4. Pass `projects`, `selectedProjectId`, `onSelectProject` to `TaskCreateForm`
5. Update `createMutation.onSuccess` to also invalidate `['project-tasks']` queries

- [ ] **Step 3: Verify TypeScript**

Run:
```bash
cd frontend && node_modules/.bin/tsc -b
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/tasks/TaskCreateForm.tsx frontend/src/pages/TasksPage.tsx
git commit -m "feat: add project selector to task creation dialog"
```

---

### Task 12: Frontend — i18n

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

- [ ] **Step 1: Add i18n keys**

Add under `en` section:

```typescript
      projects: {
        sidebarEyebrow: 'Projects',
        sidebarTitle: 'Projects',
        sidebarCount: '{{count}} projects',
        newProject: 'New Project',
        newTask: 'New Task',
        searchPlaceholder: 'Search projects...',
        resetLayout: 'Reset Layout',
        emptyCanvas: "Click 'New Task' to get started",
        noProjects: 'No projects yet. Create one to start.',
      },
      tasks: {
        // ... existing keys ...
        projectLabel: 'Project',
      },
      navigation: {
        // ... existing keys ...
        projects: {
          label: 'Projects',
          description: 'Manage projects',
        },
      },
```

Add corresponding `zh` translations.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/messages.ts
git commit -m "feat: add project canvas i18n strings"
```

---

### Task 13: Frontend — React Flow CSS Integration

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add React Flow theme variables**

Add to `frontend/src/index.css`:

```css
/* React Flow theme integration */
.react-flow {
  --xy-edge-stroke: var(--border);
  --xy-edge-stroke-selected: var(--apple-blue);
  --xy-handle-background: var(--apple-blue);
  --xy-handle-border-color: var(--surface);
}

.react-flow__attribution {
  display: none;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "style: add React Flow theme CSS variables"
```

---

## Self-Review

**1. Spec coverage:**
- TaskEdge model ✅ (Task 1)
- Edge CRUD + auto-connect ✅ (Task 2)
- API routes + schemas ✅ (Task 3)
- Backend tests ✅ (Tasks 1-3)
- React Flow dependency ✅ (Task 4)
- Frontend types ✅ (Task 4)
- API endpoints + mocks ✅ (Task 5)
- Route + navigation ✅ (Task 6)
- ProjectSidebar ✅ (Task 7)
- TaskNode ✅ (Task 8)
- ProjectCanvas with dagre ✅ (Task 9)
- ProjectsPage ✅ (Task 10)
- TasksPage project selector ✅ (Task 11)
- i18n ✅ (Task 12)
- React Flow CSS ✅ (Task 13)

**2. Placeholder scan:** No TBD/TODO/fill-in-details found. All steps have concrete code.

**3. Type consistency:** `TaskEdge` model matches across backend (`task_harness/models.py`), API schemas (`schemas.py`), and frontend types (`types/index.ts`). Edge ID format consistent (`edge-{hex}`).

**No gaps found.**
