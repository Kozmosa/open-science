# Database Index Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 18 `CREATE INDEX IF NOT EXISTS` statements across 3 service files to eliminate 24 missing SQLite indexes identified by the perf audit toolchain.

**Architecture:** Each index is added via a single `conn.execute()` call placed after the relevant `CREATE TABLE` statements in the service's `initialize()` method. All indexes use `IF NOT EXISTS` for idempotency.

**Tech Stack:** Python 3.13, SQLite (via sqlite3 stdlib)

---

### Task 1: Auth Service Indexes

**Files:**
- Modify: `src/ainrf/auth/service.py:86-98`

- [ ] **Step 1: Add 3 indexes to auth service**

Insert after `conn.execute("CREATE INDEX IF NOT EXISTS idx_env_access_user ...")` (line 91) and before the migration block (line 92):

```python
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
            )
```

- [ ] **Step 2: Run auth tests to verify**

```bash
uv run pytest tests/test_api_auth.py -v -q
```

Expected: all auth tests pass, no sqlite errors on index creation.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/auth/service.py
git commit -m "perf: add indexes on users.status, refresh_tokens.user_id, refresh_tokens.expires_at"
```

---

### Task 2: Task Harness Service Indexes

**Files:**
- Modify: `src/ainrf/task_harness/service.py:255-257`

- [ ] **Step 1: Add 10 indexes to task_harness service**

Insert after `connection.commit()` on line 256 (end of `task_harness_session_states` CREATE TABLE) and before `self._fail_unfinished_tasks_for_restart()` on line 257:

```python
            # Performance indexes
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON task_harness_tasks(project_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON task_harness_tasks(session_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_environment_id ON task_harness_tasks(environment_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_workspace_id ON task_harness_tasks(workspace_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_owner_user_id ON task_harness_tasks(owner_user_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON task_harness_tasks(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_project_id ON task_harness_edges(project_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_source ON task_harness_edges(source_task_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_edges_target ON task_harness_edges(target_task_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_output_events_kind ON task_harness_output_events(kind)"
            )
            connection.commit()
```

- [ ] **Step 2: Run task harness and task-related API tests**

```bash
uv run pytest tests/test_api_tasks.py tests/test_task_edges.py -v -q
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/task_harness/service.py
git commit -m "perf: add indexes on task_harness_tasks, task_harness_edges, task_harness_output_events"
```

---

### Task 3: Sessions Service Indexes

**Files:**
- Modify: `src/ainrf/sessions/service.py:66-74`

- [ ] **Step 1: Add 4 indexes to sessions service**

Insert after the existing `idx_attempts_session` index (line 69) and before the migration ALTER TABLE block:

```python
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON task_sessions(project_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON task_sessions(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attempts_parent ON task_attempts(parent_attempt_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_attempts_status ON task_attempts(status)"
            )
```

- [ ] **Step 2: Run sessions tests to verify**

```bash
uv run pytest tests/test_sessions.py -v -q
```

Expected: all sessions tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/sessions/service.py
git commit -m "perf: add indexes on task_sessions(project_id, status), task_sessions(created_at), task_attempts(parent_attempt_id), task_attempts(status)"
```

---

### Task 4: Integration Verification

- [ ] **Step 1: Full backend test suite**

```bash
uv run pytest tests/ -q --deselect tests/api/test_files_routes.py::test_read_file_too_large --deselect tests/test_cli.py::test_serve_rejects_malformed_config_with_validation_error
```

Expected: all tests pass (skipping 2 pre-existing unrelated failures).

- [ ] **Step 2: Re-run DB index audit to confirm all 24 missing indexes are gone**

```bash
uv run python scripts/perf/run-all.py --target db
```

Expected: `db-index-report.md` shows 0 missing indexes and 0 full table scans.

- [ ] **Step 3: Read and confirm the report**

```bash
cat .cache/perf-report/$(date +%Y-%m-%d)/db-summary.json
```

Expected: all `missing_index_count` values are 0.

- [ ] **Step 4: Commit**

```bash
git add docs/LLM-Working/worklog/2026-05-20.md
git commit -m "chore: update worklog with DB index optimization verification"
```

---

## Verification Checklist

1. `uv run pytest tests/ -q` — backend tests pass (skipping 2 pre-existing failures)
2. `uv run python scripts/perf/run-all.py --target db` — 0 missing indexes, 0 full table scans
3. `cd frontend && node_modules/.bin/tsc -b` — frontend type check passes
4. All index names follow `idx_<table>_<column>` convention
