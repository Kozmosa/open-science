# Auth Phase B — Resource Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add owner_user_id to all resources, project_collaborators + environment_access tables, permissions.py enforcement, route handler filtering, and admin user management.

**Architecture:** Extend AuthService with user management methods + collaborator/env_access tables. Add permissions.py with require_admin / check_project_access / check_environment_access helpers. Each route handler gets `get_current_user(request)` and enforces ownership filtering on List/Create/Read/Write/Delete.

**Tech Stack:** Python 3.13 dataclasses, SQLite3, FastAPI, React 19 (minimal changes)

---

## Task 1: AuthService Extensions + Collaborator/Environment Tables

**Files:**
- Modify: `src/ainrf/auth/service.py`

- [ ] **Step 1: Read current service.py**

Read `src/ainrf/auth/service.py` to understand existing patterns.

- [ ] **Step 2: Add tables to initialize()**

In the `initialize()` method, add after existing CREATE TABLE statements:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS project_collaborators (
        project_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'member',
        added_by_user_id TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (project_id, user_id)
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS environment_access (
        environment_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        max_concurrent_tasks INTEGER,
        granted_by_user_id TEXT NOT NULL,
        granted_at TEXT NOT NULL,
        PRIMARY KEY (environment_id, user_id)
    )
""")
```

- [ ] **Step 3: Add admin user management methods**

```python
def list_users(self) -> list[User]:
    self.initialize()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_user(r) for r in rows]

def activate_user(self, user_id: str) -> User:
    self.initialize()
    now = _now_iso()
    with self._connect() as conn:
        conn.execute(
            "UPDATE users SET status = 'active', activated_at = ? WHERE id = ?",
            (now, user_id),
        )
        conn.commit()
    return self._load_user(user_id)

def disable_user(self, user_id: str) -> User:
    self.initialize()
    with self._connect() as conn:
        conn.execute(
            "UPDATE users SET status = 'disabled' WHERE id = ?",
            (user_id,),
        )
        conn.commit()
    return self._load_user(user_id)

def reset_password(self, user_id: str, new_password: str) -> None:
    self.initialize()
    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    with self._connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        conn.commit()
```

- [ ] **Step 4: Add collaborator management methods**

```python
def add_collaborator(self, *, project_id: str, user_id: str, role: str, added_by: str) -> None:
    self.initialize()
    now = _now_iso()
    with self._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_collaborators (project_id, user_id, role, added_by_user_id, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, user_id, role, added_by, now),
        )
        conn.commit()

def remove_collaborator(self, project_id: str, user_id: str) -> None:
    self.initialize()
    with self._connect() as conn:
        conn.execute(
            "DELETE FROM project_collaborators WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        conn.commit()

def list_collaborators(self, project_id: str) -> list[dict]:
    self.initialize()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT pc.*, u.username, u.display_name "
            "FROM project_collaborators pc JOIN users u ON pc.user_id = u.id "
            "WHERE pc.project_id = ?",
            (project_id,),
        ).fetchall()
    return [{"user_id": r["user_id"], "username": r["username"],
             "display_name": r["display_name"], "role": r["role"]} for r in rows]

def get_user_project_ids(self, user_id: str) -> list[str]:
    """Returns all project_ids the user has access to (owner or collaborator)."""
    self.initialize()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT project_id FROM project_collaborators WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [r["project_id"] for r in rows]
```

- [ ] **Step 4: Add environment access methods**

```python
def grant_environment(self, *, env_id: str, user_id: str, max_tasks: int | None, granted_by: str) -> None:
    self.initialize()
    now = _now_iso()
    with self._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO environment_access "
            "(environment_id, user_id, max_concurrent_tasks, granted_by_user_id, granted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (env_id, user_id, max_tasks, granted_by, now),
        )
        conn.commit()

def revoke_environment(self, env_id: str, user_id: str) -> None:
    self.initialize()
    with self._connect() as conn:
        conn.execute(
            "DELETE FROM environment_access WHERE environment_id = ? AND user_id = ?",
            (env_id, user_id),
        )
        conn.commit()

def get_user_environment_ids(self, user_id: str) -> list[str]:
    self.initialize()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT environment_id FROM environment_access WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [r["environment_id"] for r in rows]
```

- [ ] **Step 5: Verify import**

Run: `cd /home/xuyang/code/scholar-agent && uv run python -c "from ainrf.auth import AuthService; print('OK')"`

- [ ] **Step 6: Run existing tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/test_auth.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/ainrf/auth/service.py
git commit -m "feat: add admin user mgmt, collaborator, and environment access methods"
```

---

## Task 2: DB Migrations — owner_user_id on All Resource Tables

**Files:**
- Modify: `src/ainrf/task_harness/service.py` — add owner_user_id column + set on create + return in serialization
- Modify: `src/ainrf/sessions/service.py` — add owner_user_id column + set on create + filter list
- Modify: `src/ainrf/projects/service.py` — add owner_user_id to JSON model + filter
- Modify: `src/ainrf/workspaces/service.py` — add owner_user_id to JSON model + filter

- [ ] **Step 1: task_harness_tasks — add owner_user_id**

In `TaskHarnessService.initialize()`, add migration:
```python
self._ensure_column(connection, "task_harness_tasks", "owner_user_id",
    "ALTER TABLE task_harness_tasks ADD COLUMN owner_user_id TEXT")
```

In `create_task()`, accept `owner_user_id: str | None = None` parameter and include it in the INSERT.

In `_row_to_list_item()` and task serialization, include `owner_user_id` field.

- [ ] **Step 2: task_sessions — add owner_user_id**

In `SessionService.initialize()`, add column to task_sessions:
```python
conn.execute("ALTER TABLE task_sessions ADD COLUMN owner_user_id TEXT")
```
(use try/except for if column already exists; or check PRAGMA table_info)

In `create_session()`, accept `owner_user_id: str | None = None` and store it.

In `list_sessions()`, add optional `owner_user_id` filter parameter.

- [ ] **Step 3: projects.json — add owner_user_id**

In `ProjectRegistryService`, add `owner_user_id: str | None = None` to the project model. Store in JSON. Add optional filter in list method.

- [ ] **Step 4: workspaces.json — add owner_user_id**

Same pattern as projects.

- [ ] **Step 5: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Expected: All pass (optional fields, no regression).

- [ ] **Step 6: Commit**

```bash
git add src/ainrf/task_harness/service.py src/ainrf/sessions/service.py src/ainrf/projects/service.py src/ainrf/workspaces/service.py
git commit -m "feat: add owner_user_id to all resource tables"
```

---

## Task 3: permissions.py + Route Handler Enforcement

**Files:**
- Create: `src/ainrf/auth/permissions.py`
- Modify: Route files for /projects, /tasks, /environments, /workspaces, /sessions, /terminal, /resources, /skills

- [ ] **Step 1: Create permissions.py**

Create `src/ainrf/auth/permissions.py`:

```python
"""Permission checking helpers for route handlers."""

from __future__ import annotations

from fastapi import HTTPException, Request


def get_current_user(request: Request) -> dict:
    """Get current user from request state. Raises 401 if not authenticated."""
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: dict) -> None:
    """Raise 403 if user is not admin."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def check_resource_owner(user: dict, owner_user_id: str | None) -> bool:
    """Check if user owns the resource. Admin sees everything."""
    if user.get("role") == "admin":
        return True
    if owner_user_id is None:
        return False  # legacy unowned data
    return owner_user_id == user["id"]
```

- [ ] **Step 2: Enforce /tasks route**

Read `src/ainrf/api/routes/tasks.py`. In each handler:

```python
from ainrf.auth.permissions import get_current_user, require_admin, check_resource_owner

# In list_tasks:
user = get_current_user(request)
if user["role"] == "admin":
    tasks = service.list_tasks(...)
else:
    tasks = service.list_tasks_by_user(user["id"])  # new method

# In create_task:
user = get_current_user(request)
task = service.create_task(..., owner_user_id=user["id"])

# In get_task / cancel / pause / resume / delete:
user = get_current_user(request)
task = service.get_task(task_id)
if not check_resource_owner(user, task.owner_user_id):
    raise HTTPException(status_code=403, detail="Access denied")
```

Add `list_tasks_by_user()` to TaskHarnessService if not already present.

- [ ] **Step 3: Enforce /projects route**

Same pattern — admin sees all, member sees owned + collaborator projects.

- [ ] **Step 4: Enforce /environments route**

Admin: full access. Member: `get_user_environment_ids()` to filter list. Create/update/delete: admin only.

- [ ] **Step 5: Enforce /workspaces, /sessions, /terminal, /resources, /skills**

Same patterns as above. Terminal: replace `_require_app_user_id()` header read with `get_current_user(request)["id"]`.

- [ ] **Step 6: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Some tests may need updating to include proper user context. Fix any failures.

- [ ] **Step 7: Commit**

```bash
git add src/ainrf/auth/permissions.py src/ainrf/api/routes/
git commit -m "feat: add permissions.py and enforce resource ownership in all routes"
```

---

## Task 4: Admin API Routes

**Files:**
- Create: `src/ainrf/api/routes/admin.py`
- Modify: `src/ainrf/api/schemas.py`
- Modify: `src/ainrf/api/app.py`

- [ ] **Step 1: Add admin schemas**

Append to `src/ainrf/api/schemas.py`:

```python
class AdminUserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None  # 'active' | 'disabled'

class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=4)

class AdminUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    username: str
    display_name: str
    role: str
    status: str
    created_at: str
    last_login_at: str | None = None

class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AdminUserResponse]
```

- [ ] **Step 2: Create admin routes**

Create `src/ainrf/api/routes/admin.py`:

```python
"""Admin API routes — user management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ainrf.api.schemas import AdminPasswordResetRequest, AdminUserListResponse, AdminUserResponse, AdminUserUpdateRequest
from ainrf.auth import AuthService
from ainrf.auth.permissions import get_current_user, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="auth service not initialized")
    return service


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(request: Request) -> AdminUserListResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    users = service.list_users()
    return AdminUserListResponse.model_validate({
        "items": [{...} for u in users],
    })


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(user_id: str, payload: AdminUserUpdateRequest, request: Request) -> AdminUserResponse:
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    if payload.status == "active":
        u = service.activate_user(user_id)
    elif payload.status == "disabled":
        u = service.disable_user(user_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid status")
    return AdminUserResponse.model_validate(_serialize_admin_user(u))


@router.put("/users/{user_id}/password", status_code=204)
async def reset_password(user_id: str, payload: AdminPasswordResetRequest, request: Request):
    user = get_current_user(request)
    require_admin(user)
    service = _get_service(request)
    service.reset_password(user_id, payload.password)
    return None
```

(Add proper serializer _serialize_admin_user that converts User dataclass to dict.)

- [ ] **Step 3: Register admin router in app.py**

Add to ROUTERS tuple and import.

- [ ] **Step 4: Run tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/api/routes/admin.py src/ainrf/api/schemas.py src/ainrf/api/app.py
git commit -m "feat: add admin API routes for user management"
```

---

## Task 5: Backend Tests + Integration Verification

**Files:**
- Create/modify: `tests/test_permissions.py`

- [ ] **Step 1: Write permission tests**

Create `tests/test_permissions.py`:

```python
"""Tests for permission enforcement."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest


class TestPermissions:
    @pytest.fixture
    def auth_svc(self):
        from ainrf.auth import AuthService
        with tempfile.TemporaryDirectory() as td:
            svc = AuthService(state_root=Path(td))
            svc.initialize()
            # Create admin
            svc.register(username="admin", display_name="Admin", password="admin123")
            svc._activate_direct("admin")
            # Create member
            svc.register(username="alice", display_name="Alice", password="alice123")
            svc._activate_direct("alice")
            yield svc

    def test_admin_can_list_all_users(self, auth_svc):
        users = auth_svc.list_users()
        assert len(users) == 2

    def test_activate_user(self, auth_svc):
        auth_svc.register(username="bob", display_name="Bob", password="bob123")
        user = auth_svc._load_user_by_username("bob")
        assert user.status.value == "pending"
        auth_svc.activate_user(user.id)
        user2 = auth_svc._load_user_by_username("bob")
        assert user2.status.value == "active"

    def test_disable_user(self, auth_svc):
        auth_svc.disable_user(auth_svc._load_user_by_username("alice").id)
        with pytest.raises(Exception) as exc:
            auth_svc.login(username="alice", password="alice123")
        assert "disabled" in str(exc.value).lower()

    def test_reset_password(self, auth_svc):
        uid = auth_svc._load_user_by_username("alice").id
        auth_svc.reset_password(uid, "newpass")
        result = auth_svc.login(username="alice", password="newpass")
        assert "access_token" in result

    def test_add_and_list_collaborators(self, auth_svc):
        # Project owner is admin, add alice as member
        auth_svc.add_collaborator(project_id="p1", user_id=auth_svc._load_user_by_username("alice").id, role="member", added_by="admin")
        collabs = auth_svc.list_collaborators("p1")
        assert len(collabs) == 1
        assert collabs[0]["role"] == "member"

    def test_remove_collaborator(self, auth_svc):
        uid = auth_svc._load_user_by_username("alice").id
        auth_svc.add_collaborator(project_id="p1", user_id=uid, role="member", added_by="admin")
        auth_svc.remove_collaborator("p1", uid)
        assert len(auth_svc.list_collaborators("p1")) == 0

    def test_environment_access_grant_revoke(self, auth_svc):
        uid = auth_svc._load_user_by_username("alice").id
        auth_svc.grant_environment(env_id="env1", user_id=uid, max_tasks=2, granted_by="admin")
        envs = auth_svc.get_user_environment_ids(uid)
        assert "env1" in envs
        auth_svc.revoke_environment("env1", uid)
        assert "env1" not in auth_svc.get_user_environment_ids(uid)

    def test_require_admin_function(self):
        from ainrf.auth.permissions import require_admin
        with pytest.raises(Exception):  # HTTPException with 403
            require_admin({"id": "u1", "role": "member"})

    def test_check_resource_owner(self):
        from ainrf.auth.permissions import check_resource_owner
        assert check_resource_owner({"id": "u1", "role": "member"}, "u1") is True
        assert check_resource_owner({"id": "u1", "role": "member"}, "u2") is False
        assert check_resource_owner({"id": "admin1", "role": "admin"}, "u2") is True
        assert check_resource_owner({"id": "u1", "role": "member"}, None) is False


class TestAuthServiceHelper:
    """Tests for helper methods added in Phase B."""
    # _activate_direct and _load_user_by_username helpers can be tested here
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/xuyang/code/scholar-agent && uv run pytest tests/ -x -q`
Run: `cd /home/xuyang/code/scholar-agent/frontend && npm run test:run`
Run: `cd /home/xuyang/code/scholar-agent/frontend && node_modules/.bin/tsc -b`
Run: `cd /home/xuyang/code/scholar-agent && uv run ruff check src/ainrf/auth/ src/ainrf/api/routes/`

- [ ] **Step 3: Commit**

```bash
git add tests/test_permissions.py
git commit -m "test: add permission enforcement tests for Phase B"
```
