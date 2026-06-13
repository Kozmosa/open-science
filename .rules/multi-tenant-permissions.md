# Multi-Tenant Permission Model

AINRF uses Linux user isolation for multi-tenancy. Understanding the
permission model is critical to avoid silent failures when modifying auth,
tenant provisioning, file handling, or any code that crosses user boundaries.

For recurring pitfalls related to permissions, see the relevant sections in
[dev-bitter-lesson.md](../dev-bitter-lesson.md).

## User Roles

- `ainrf` (uid=1000) — the backend process user. Owns `/opt/ainrf/state/`, `/opt/ainrf/.ainrf_workspaces/`.
- `ainrf_<username>` (gid=2000/`ainrf_tenants`) — one Linux user per registered tenant. Home at `/home/ainrf_tenants/<username>/` with mode `0700`.
- `root` — runs entrypoint.py which provisions tenant users, homes, and workspace directories.

## Execution Flow

1. Backend (ainrf) receives task → resolves `tenant_user = ainrf_<owner>`
2. Engine builds command → prefixes with `sudo -u ainrf_<owner>`
3. `sudoers` grants: `ainrf ALL=(%ainrf_tenants) NOPASSWD: ALL`
4. Agent process (claude/codex) runs as tenant user with tenant's workspace as cwd

## Permission Constraints

- `ainrf` **cannot write** to tenant home dirs (mode 0700, owned by tenant)
- `ainrf` **cannot write** to tenant workspace dirs (owned by tenant, group ainrf_tenants, ainrf is not in that group)
- Any file/directory creation by `ainrf` inside tenant paths will EPERM
- Temp files created by `ainrf` (e.g., MCP config) must be `chmod 0644` if tenant subprocess needs to read them
- `sudo -u <tenant>` does NOT inherit `ainrf`'s env vars for API keys — these must be explicitly passed via the engine's env setup

## Known Permission-Sensitive Code Paths

| Path | Operation | Status |
|------|-----------|--------|
| `claude_code.py` | MCP config temp file → chmod 0644 | Fixed |
| `claude_code.py` | `_prepare_workspace_skills` creates dirs/symlinks via `sudo -u <tenant>` | Fixed |
| `service.py` | `_resolve_working_directory` uses `sudo -u <tenant> mkdir -p` for tenant workspaces | Fixed |
| `workspaces/service.py` | `ensure_tenant_workspace` uses `sudo -u <tenant> mkdir -p` | Fixed |
| `auth/service.py` | `provision_tenant_user` mkdir + chown | OK — runs during registration |
| `files.py` | Upload → chown to tenant | Fixed |
| `agent_sdk.py` | No `user=` param (removed) | Fixed |

## Guidelines for New Code

- Never assume `ainrf` can write to `/home/ainrf_tenants/<username>/` paths
- If a file must be readable by a tenant subprocess (via `sudo -u`), set `chmod 0644` after creation
- If a directory must be created in tenant space, use `subprocess.run(["sudo", "-u", tenant_user, "mkdir", "-p", path])`
- Workspace dirs for new labels should be created via the tenant user, not directly by ainrf
