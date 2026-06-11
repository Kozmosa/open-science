# Backup & Restore Plan

## Problem

There is no backup or restore mechanism for AINRF business data. A single `docker volume rm`,
a failed migration, or an accidental container rebuild loses all user accounts, tasks,
terminal sessions, and workspace files.

## Data Inventory

| Data | Location | Size Profile | Backup Frequency |
|------|----------|-------------|------------------|
| auth.sqlite3 | /opt/ainrf/state/runtime/ | <1 MB | Every change |
| sessions.sqlite3 | /opt/ainrf/state/runtime/ | <10 MB | Hourly |
| agentic_researcher.sqlite3 | /opt/ainrf/state/runtime/ | <100 MB | Hourly |
| terminal_state.sqlite3 | /opt/ainrf/state/runtime/ | <1 MB | Hourly |
| workspaces.json | /opt/ainrf/state/runtime/ | <10 KB | Every change |
| Tenant homes | /home/ainrf_tenants/ | Variable | Daily |
| Workspace files | /opt/ainrf/.ainrf_workspaces/ | Variable | Daily |
| task_harness.sqlite3 (legacy) | /opt/ainrf/state/runtime/ | <100 MB | Once (archive) |

## Design

### 1. SQLite Backup — `sqlite3 .backup` API

Use Python's `sqlite3.Connection.backup()` for consistent snapshots without locking the
live database. This is the official SQLite backup mechanism — it works on a live DB without
blocking writes.

```python
def backup_database(db_path: Path, backup_path: Path) -> None:
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup_path))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
```

### 2. Backup Storage Layout

```
/opt/ainrf/state/backups/
  daily/
    2026-06-11T030000.tar.gz
  pre-migration/
    2026-06-11T142356.tar.gz          # automatic before schema migration
  manual/
    2026-06-11T100000.tar.gz          # user-triggered
```

Each tarball contains:
```
runtime/auth.sqlite3
runtime/sessions.sqlite3
runtime/agentic_researcher.sqlite3
runtime/terminal_state.sqlite3
runtime/workspaces.json
runtime/task_harness.sqlite3          # if exists
metadata.json                         # {version, timestamp, sizes}
```

Tenant homes and workspace files are backed up separately (file-level, not in the tarball).

### 3. Backup Module — `ainrf/backup.py`

```python
def create_backup(state_root: Path, label: str = "manual") -> Path:
    """Create a backup of all databases and registry files.
    Returns path to the .tar.gz backup file."""

def restore_backup(state_root: Path, backup_path: Path) -> None:
    """Restore databases from a backup file. Stops the server first."""

def list_backups(state_root: Path) -> list[BackupInfo]:
    """List available backups with metadata."""

def prune_backups(state_root: Path, *, keep_daily: int = 7, keep_weekly: int = 4) -> int:
    """Remove old backups, keeping the most recent N daily and N weekly."""

def pre_migration_backup(state_root: Path) -> Path:
    """Create a backup before schema migration runs."""
```

### 4. CLI Commands

```bash
# Create a manual backup
ainrf backup create [--label <label>]

# List available backups
ainrf backup list

# Restore from a specific backup
ainrf backup restore <backup-file>

# Prune old backups
ainrf backup prune [--keep-daily 7] [--keep-weekly 4]

# Show backup status and disk usage
ainrf backup status
```

### 5. Entrypoint Integration

In `deploy/config/entrypoint.py`, before running tenant provisioning and before the server
starts:

```
container start
  ↓
entrypoint (root)
  ↓
ainrf backup create --label pre-start       # lightweight: SQLite only
  ↓
_provision_tenant_users()
  ↓
drop privileges
  ↓
ainrf db migrate                            # triggers pre-migration backup
  ↓
exec ainrf serve
```

### 6. Scheduled Daily Backup

A cron-like mechanism inside the container using asyncio scheduling (already in the server
process):

```python
# In app.py lifespan, after services are initialized:
from ainrf.backup import scheduled_backup
asyncio.create_task(scheduled_backup(state_root, interval_hours=24))
```

`scheduled_backup` runs a backup every 24 hours (configurable via env `AINRF_BACKUP_INTERVAL_HOURS`),
rotating with `prune_backups(keep_daily=7, keep_weekly=4)`.

### 7. File-Level Backup for Tenant Homes

Tenant homes and workspace files use **tar + incremental** backup:

```bash
# Full backup (first run)
tar czf /opt/ainrf/state/backups/daily/files-full.tar.gz -C / home/ainrf_tenants/

# Incremental via GNU tar
tar czf /opt/ainrf/state/backups/daily/files-inc-$(date +%Y%m%d).tar.gz \
  --listed-incremental=/opt/ainrf/state/backups/.files-snapshot \
  -C / home/ainrf_tenants/
```

This is called from `ainrf backup create --include-files`.

### 8. Restore Procedure

```bash
# 1. Stop the container
docker compose down

# 2. List available backups
docker run --rm -v ainrf-state:/opt/ainrf/state ainrf:latest \
  ainrf backup list

# 3. Restore (replaces live DB files from backup tarball)
docker run --rm -v ainrf-state:/opt/ainrf/state ainrf:latest \
  ainrf backup restore /opt/ainrf/state/backups/manual/2026-06-11T100000.tar.gz

# 4. Restore tenant files (if --include-files was used)
tar xzf files-full.tar.gz -C /

# 5. Start the container
docker compose up -d
# entrypoint auto-provisions tenant Linux users from restored auth DB
```

## Implementation Steps

### Phase 1: Core Backup Module

1. Create `src/ainrf/backup.py` with:
   - `create_backup()` — SQLite .backup() + tar + metadata.json
   - `restore_backup()` — stop check + extract tar + verify metadata
   - `list_backups()` — parse metadata.json from each tarball
   - `prune_backups()` — delete old backups with retention policy
2. Tests: create/restore round-trip, prune logic, corrupt backup handling

### Phase 2: CLI Commands

1. Add `backup` subcommand group to `ainrf/cli.py`
2. `backup create`, `backup list`, `backup restore`, `backup prune`, `backup status`
3. Tests: CLI smoke tests

### Phase 3: Entrypoint Pre-Start Backup

1. Add `ainrf backup create --label pre-start` to entrypoint before provisioning
2. Only backs up SQLite (fast, <5 seconds)
3. Keeps last 3 pre-start backups, prunes older ones

### Phase 4: Scheduled Daily Backup

1. Add `scheduled_backup()` async task to app lifespan
2. Configurable via `AINRF_BACKUP_INTERVAL_HOURS` env var (default 24)
3. Runs `prune_backups()` after each backup
4. Disable with `AINRF_BACKUP_ENABLED=false`

### Phase 5: File-Level Backup

1. Add `--include-files` flag to `ainrf backup create`
2. Uses GNU tar incremental backup for tenant homes
3. Adds tenant files to the same tarball or a separate one

### Phase 6: Docker Integration

1. Add `deploy/scripts/backup.sh` for external cron scheduling
2. Add backup volume to docker-compose (optional external backup storage)
3. Document restore procedure in deploy README

## Retention Policy

| Label | Keep | Frequency |
|-------|------|-----------|
| pre-start | 3 | Every container start |
| pre-migration | all | Before every schema migration |
| daily | 7 | Every 24 hours |
| weekly | 4 | Sunday rotation |
| manual | all | User-triggered, never auto-deleted |

## Estimated Sizes

| Component | Live Size | Compressed Backup |
|-----------|-----------|-------------------|
| All SQLite DBs | ~100 MB | ~20 MB |
| Tenant homes (10 users) | ~500 MB | ~100 MB |
| Workspace files | Varies | Varies |
| **Total daily backup** | | **~120 MB** |

With 7 daily + 4 weekly retention: ~1.5 GB disk overhead.

## File Layout

```
src/ainrf/backup.py                         # Backup/restore logic
src/ainrf/cli.py                            # CLI commands (add backup subcommand)
tests/test_backup.py                        # Backup module tests
deploy/scripts/backup.sh                    # External cron wrapper
```
