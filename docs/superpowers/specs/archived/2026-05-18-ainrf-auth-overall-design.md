# AINRF Multi-User Auth — Overall Architecture

> [!warning] Historical specification
> 本文已归档，不再定义当前产品 contract。请以 `PROJECT_BASIS.md`、`docs-site/docs/`、代码与活跃 spec 为准；原文保留用于解释历史决策和迁移来源。

Date: 2026-05-18 | Session: `ainrf-h2` | Status: reference (for Phase B and C)

## Key Decisions (confirmed)

| Dimension | Choice |
|-----------|--------|
| Scale | Small team shared deployment (2-10 users, same machine) |
| Auth method | Username + password → JWT (replace API Key) |
| Permission model | Owner-based + Project Collaborators (member/viewer) + Admin(PI) |
| Environments | Admin-managed, permission groups + per-user quotas |
| Workspaces | User-private default, project-shared via collaborator access |
| User creation | Open registration + Admin approval |
| Auth for CLI | `ainrf login` → token cached in `~/.ainrf/token` |

## Phases

### Phase A (this spec) — User System + JWT + Login
- auth.sqlite3 + User table + refresh_tokens
- AuthService + JWT middleware
- Frontend Login/Register + AuthContext
- CLI `ainrf login`

### Phase B — Resource Isolation + Permissions
- All resource tables: + owner_user_id
- project_collaborators + environment_access tables
- permissions.py: require_admin, check_project_access, check_environment_access
- Route handler permission enforcement

### Phase C — Admin UI + Collaborators
- Admin Settings → Users tab (approve/disable/reset password)
- Admin Settings → Environment permission groups UI
- Project Collaborators management UI
- Per-project cost summary dashboard

## Data Model (all phases)

See visual companion pages for full ER diagrams.

## Visual Companion

`docs/superpowers/specs/2026-05-18-ainrf-auth/visual-companion/`
