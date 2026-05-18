# AINRF Multi-User Auth — Phase B Design Spec

Date: 2026-05-18 | Session: `ainrf-h2` | Status: draft
Part of: Multi-User Auth (Phase B/3) | Prev: Phase A (User System + JWT) | Next: Phase C (Admin UI + Collaborators)

## Phase B Scope

Resource isolation and permission enforcement. All existing resources become user-scoped.

- DB migrations: all resource tables + owner_user_id, new project_collaborators + environment_access tables
- AuthService extensions: admin user management, collaborator CRUD, environment access CRUD
- permissions.py: require_admin, check_project_access, check_environment_access
- Route handler enforcement: List filter by user, Create set owner, Read/Write/Delete check access
- Admin API endpoints for user management

## Data Model Changes

### Resource Tables — ALTER TABLE ADD owner_user_id TEXT

All columns default NULL (NULL = owned by nobody, Admin-visible legacy data).

| Table | Service |
|-------|---------|
| task_harness_tasks | TaskHarnessService.initialize() |
| task_sessions | SessionService.initialize() |
| projects (JSON file) | ProjectRegistryService — JSON field |
| workspaces (JSON file) | WorkspaceRegistryService — JSON field |

### New Tables (auth.sqlite3, added in AuthService.initialize())

```sql
CREATE TABLE IF NOT EXISTS project_collaborators (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',  -- 'member' | 'viewer'
    added_by_user_id TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS environment_access (
    environment_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    max_concurrent_tasks INTEGER,  -- NULL = unlimited
    granted_by_user_id TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    PRIMARY KEY (environment_id, user_id)
);
```

## AuthService Extensions

```python
# Admin user management
def list_users(self) -> list[User]
def activate_user(self, user_id: str) -> User
def disable_user(self, user_id: str) -> User
def reset_password(self, user_id: str, new_password: str) -> None

# Collaborator management
def add_collaborator(self, project_id: str, user_id: str, role: str, added_by: str) -> None
def remove_collaborator(self, project_id: str, user_id: str) -> None
def list_collaborators(self, project_id: str) -> list[dict]

# Environment access
def grant_environment(self, env_id: str, user_id: str, max_tasks: int | None, granted_by: str) -> None
def revoke_environment(self, env_id: str, user_id: str) -> None
def list_environment_users(self, env_id: str) -> list[dict]
def get_user_environments(self, user_id: str) -> list[str]  # returns env_ids
```

## Permissions (src/ainrf/auth/permissions.py)

```python
def get_current_user(request: Request) -> dict
def require_admin(user: dict) -> None  # raises 403
def check_project_access(auth_service, user: dict, project_id: str, min_role: str | None = None) -> bool
def check_environment_access(auth_service, user: dict, env_id: str) -> bool
```

## Route Handler Changes

Each route handler:
1. Gets `user = get_current_user(request)` 
2. List endpoints: filter by user (admin sees all, member sees own + collaborator resources)
3. Create endpoints: set `owner_user_id = user["id"]`
4. Read/Write/Delete: call permission check, return 403 on failure

### /projects
- List: admin sees all, member sees owned + collaborator projects
- Create: owner_user_id = self, can create freely
- Get/Patch/Delete: admin or owner or project member

### /tasks
- List: admin sees all, member sees owned tasks + tasks in collaborator projects
- Create: owner_user_id = self, requires project access
- Get/Cancel/Pause/Resume/Delete: admin or owner or project member

### /environments
- List: admin sees all, member sees granted environments
- Create/Update/Delete: admin only
- Detect: member can detect own granted environments

### /workspaces
- List: admin sees all, member sees owned + collaborator project workspaces
- Create: owner_user_id = self
- Get/Patch/Delete: admin or owner or project collaborator

### /sessions
- List: admin sees all, member sees owned sessions
- Create: owner_user_id = self
- Get/Patch/Delete: owner only

### /terminal
- Replace `X-AINRF-User-Id` header with `request.state.current_user["id"]`
- User-scoping already exists in SessionManager, just update the identity source

### /skills
- List/Get: unrestricted (shared knowledge)
- Import: admin only

### /resources
- List: admin sees all, member sees resources for granted environments

## Admin API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /admin/users | List all users |
| PATCH | /admin/users/{id} | Activate (status=active) or disable (status=disabled) |
| PUT | /admin/users/{id}/password | Reset password |

All require admin role (checked via require_admin).

## Implementation Order

1. AuthService extensions: user management + collaborator CRUD + environment access CRUD
2. DB migrations: ALTER TABLE owner_user_id on all resource tables
3. permissions.py: helper functions
4. Route handler enforcement — /projects, /tasks, /environments, /workspaces, /sessions, /terminal, /skills, /resources
5. Admin API routes + schemas
6. Tests + Integration verification

## Testing

### Backend
- Admin can list/activate/disable/reset password
- Non-admin cannot call admin endpoints (403)
- Create resource sets owner_user_id
- List returns only own resources for member, all for admin
- Non-owner cannot modify/delete others' resources
- Project collaborator can access project resources
- Viewer cannot modify (read-only)
- Environment access grant/revoke
- Terminal uses JWT user_id
- NULL owner resources visible to admin only

### Frontend (minimal Phase B changes)
- Admin Settings: Users tab visible only for admin
- No other frontend changes needed (resource filtering is transparent via API)
