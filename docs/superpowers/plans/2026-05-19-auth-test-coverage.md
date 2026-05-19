# Auth Test Coverage Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add tests for Collaborator CRUD, Environment Access CRUD, Admin user management API, and UsersTab/EnvAccessTab components.

## Task 1: Backend Collaborator + Env Access + Admin Tests

**Files:**
- Modify: `tests/test_permissions.py`

Extend `tests/test_permissions.py` with 3 new test classes:

### TestCollaboratorCrud

```python
class TestCollaboratorCrud:
    @pytest.fixture
    def auth_svc(self):
        from ainrf.auth import AuthService
        with tempfile.TemporaryDirectory() as td:
            svc = AuthService(state_root=Path(td))
            svc.initialize()
            yield svc

    def test_add_and_list_collaborator(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.add_collaborator(project_id="p1", user_id=uid, role="member", added_by="admin")
        collabs = auth_svc.list_collaborators("p1")
        assert len(collabs) == 1
        assert collabs[0]["role"] == "member"
        assert collabs[0]["user_id"] == uid

    def test_remove_collaborator(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.add_collaborator(project_id="p1", user_id=uid, role="member", added_by="admin")
        auth_svc.remove_collaborator("p1", uid)
        assert len(auth_svc.list_collaborators("p1")) == 0

    def test_get_user_project_ids(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.add_collaborator(project_id="p1", user_id=uid, role="viewer", added_by="admin")
        auth_svc.add_collaborator(project_id="p2", user_id=uid, role="member", added_by="admin")
        project_ids = auth_svc.get_user_project_ids(uid)
        assert "p1" in project_ids
        assert "p2" in project_ids
```

### TestEnvironmentAccessCrud

```python
class TestEnvironmentAccessCrud:
    @pytest.fixture
    def auth_svc(self):
        ... # same fixture

    def test_grant_and_list(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.grant_environment(env_id="env1", user_id=uid, max_tasks=2, granted_by="admin")
        env_ids = auth_svc.get_user_environment_ids(uid)
        assert "env1" in env_ids

    def test_revoke(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.grant_environment(env_id="env1", user_id=uid, max_tasks=2, granted_by="admin")
        auth_svc.revoke_environment("env1", uid)
        assert "env1" not in auth_svc.get_user_environment_ids(uid)

    def test_grant_unlimited_tasks(self, auth_svc):
        uid = _ensure_user(auth_svc, "bob", "bob123")
        auth_svc.grant_environment(env_id="env2", user_id=uid, max_tasks=None, granted_by="admin")
        env_ids = auth_svc.get_user_environment_ids(uid)
        assert "env2" in env_ids
```

### TestAdminUserManagement (extends existing)

```python
class TestAdminUserManagement:
    def test_list_all_users(self, auth_svc):
        _ensure_user(auth_svc, "alice", "alice123")
        _ensure_user(auth_svc, "bob", "bob123")
        users = auth_svc.list_users()
        assert len(users) >= 2

    def test_activate_pending_user(self, auth_svc):
        user = auth_svc.register(username="charlie", display_name="Charlie", password="pw123")
        assert user.status.value == "pending"
        activated = auth_svc.activate_user(user.id)
        assert activated.status.value == "active"

    def test_disable_active_user(self, auth_svc):
        uid = _ensure_user(auth_svc, "dave", "dave123")
        disabled = auth_svc.disable_user(uid)
        assert disabled.status.value == "disabled"

    def test_reset_password(self, auth_svc):
        uid = _ensure_user(auth_svc, "eve", "oldpass")
        auth_svc.reset_password(uid, "newpass")
        result = auth_svc.login(username="eve", password="newpass")
        assert "access_token" in result
```

Helper:
```python
def _ensure_user(auth_svc, username, password):
    """Create and activate a user, return their id."""
    try:
        user = auth_svc.register(username=username, display_name=username, password=password)
    except Exception:
        user = auth_svc._load_user_by_username(username)  # already exists
    if user.status.value != "active":
        auth_svc.activate_user(user.id)
    return user.id
```

## Task 2: Frontend Tests

**Files:**
- Modify: `frontend/src/pages/SettingsPage.test.tsx`

Add tests for Users tab and EnvAccess tab visibility (with admin mock user).

## Integration Verification

Run all tests: backend + frontend.
