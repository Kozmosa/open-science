# Schema Migration Plan

## Problem

All four SQLite databases use implicit schema migration: `CREATE TABLE IF NOT EXISTS` + ad-hoc
`ALTER TABLE ADD COLUMN` wrapped in `try/except`. There is no version tracking, no migration
history, and no ability to roll back. Adding a new column requires manual `_ensure_column`
boilerplate, and incompatible schema changes (e.g., adding `NOT NULL` without a default) crash
startup with no recovery path.

## Current State

| DB | Service | Schema versioning | Migrations |
|---|---------|-------------------|------------|
| auth.sqlite3 | AuthService | ❌ none | 1 ad-hoc ALTER TABLE |
| sessions.sqlite3 | SessionService | ❌ none | 1 ad-hoc ALTER TABLE |
| agentic_researcher.sqlite3 | AgenticResearcherService | ❌ none | 2 _ensure_column + _migrate_legacy_task_statuses |
| terminal_state.sqlite3 | SessionManager | ❌ none | 0 |
| task_harness.sqlite3 (legacy) | — | ❌ none | index-only migration |

## Design

### 1. Schema Version via `PRAGMA user_version`

Each database gets a `user_version` integer that tracks the current schema revision.
`initialize()` reads the version, then runs only the migrations that haven't been applied yet.

```
version 0 → fresh DB, CREATE TABLE IF NOT EXISTS creates all tables
version 1 → add must_change_password column to users
version 2 → add owner_user_id to task_sessions
...
```

### 2. Migration Registry

Each service defines an ordered list of migration functions:

```python
# In auth/service.py
_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "add_must_change_password", _migrate_v1_add_must_change_password),
    (2, "add_login_attempts_table", _migrate_v2_add_login_attempts_table),
]
```

Each migration function is a plain `def migrate(conn) -> None` that takes a connection
with an active transaction and applies exactly one change.

### 3. Migration Runner

A shared helper in `ainrf/db.py`:

```python
def run_migrations(
    conn: sqlite3.Connection,
    db_name: str,
    migrations: list[tuple[int, str, Callable[[sqlite3.Connection], None]]],
) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, label, fn in migrations:
        if current < version:
            fn(conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            _LOG.info("Migrated %s to v%d: %s", db_name, version, label)
```

### 4. Migration Logging

Every migration writes a row to a `_migration_log` table (created by the runner):

```sql
CREATE TABLE IF NOT EXISTS _migration_log (
    version INTEGER NOT NULL,
    label TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
```

This provides an audit trail independent of `PRAGMA user_version`.

## Implementation Steps

### Phase 1: Foundation (ainrf/db.py)

1. Create `src/ainrf/db.py` with:
   - `run_migrations(conn, db_name, migrations)`
   - `ensure_migration_log(conn)`
   - `get_current_version(conn) -> int`
   - `get_migration_history(conn) -> list[dict]`
2. Tests: fresh DB, partial migration, already-migrated, failed migration rollback

### Phase 2: Migrate Auth (auth/service.py)

1. Move existing `CREATE TABLE` into a `_migrate_v0_initial(conn)` function
2. Move `ALTER TABLE users ADD COLUMN must_change_password` into `_migrate_v1_...`
3. Move `CREATE TABLE login_attempts` into `_migrate_v2_...`
4. Replace `initialize()` body with: `CREATE TABLE IF NOT EXISTS _migration_log` + `run_migrations()`
5. Verify: fresh install, upgrade from old DB, already-current DB

### Phase 3: Migrate Sessions (sessions/service.py)

1. Same pattern: extract CREATE TABLE → v0, ALTER TABLE → v1
2. Replace `initialize()` body

### Phase 4: Migrate Tasks (agentic_researcher/service.py)

1. Extract CREATE TABLE tasks + task_outputs → v0
2. _ensure_column(latest_output_seq) → v1
3. _ensure_column(token_usage_json) → v2
4. _migrate_legacy_task_statuses → v3
5. indexes → v4
6. Remove `_ensure_column` helper, remove inline `_migrate_legacy_task_statuses` call

### Phase 5: Migrate Terminal (terminal/sessions.py)

1. Two CREATE TABLEs → v0
2. Straightforward — no existing migrations

### Phase 6: CLI Command

Add `ainrf db status` and `ainrf db migrate` CLI commands:

```
$ ainrf db status
auth.sqlite3         v2  (3 migrations applied)
sessions.sqlite3     v1  (2 migrations applied)
agentic_researcher   v4  (5 migrations applied)
terminal_state       v0  (2 migrations applied)

$ ainrf db migrate
Migrating auth.sqlite3: v2 → v3 (add_user_avatar) ... done
All databases up to date.
```

### Phase 7: Entrypoint Integration

Add `ainrf db migrate` to entrypoint before server start (after tenant provisioning).

## Error Handling

- Each migration runs in its own transaction (`conn.commit()` after `PRAGMA user_version`)
- If a migration fails, it raises → server won't start → admin sees error + version number
- The migration_log shows exactly which version failed
- Manual recovery: `sqlite3 <db> "PRAGMA user_version = <last_good>"` to re-run

## Rollback Strategy

Explicit rollbacks are not implemented (SQLite DDL is hard to reverse). Instead:
- **Pre-migration backup** (covered in backup plan) ensures data safety
- Failed migrations block startup with a clear error message
- Admin can restore from backup if needed

## File Layout

```
src/ainrf/db.py                              # Migration runner + helpers
src/ainrf/auth/migrations.py                 # Auth migration functions
src/ainrf/sessions/migrations.py             # Session migration functions
src/ainrf/agentic_researcher/migrations.py   # Task migration functions
src/ainrf/terminal/migrations.py             # Terminal migration functions
tests/test_db_migrations.py                  # Migration framework tests
tests/test_auth_migrations.py                # Auth migration tests
```
