# N+1 Query and Sync I/O Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 performance bottlenecks across 4 files: 2 N+1 query patterns in terminal session manager, 3 sync I/O blocks in async paths, 1 blocking health check.

**Architecture:** Each fix is a localized change within a single file. `_load_pairs_batch()` uses SQL `IN` clause for bulk loading. Thread offloading uses `anyio.to_thread.run_sync` (already a dependency). Async health check uses `httpx.AsyncClient` (already a dependency).

**Tech Stack:** Python 3.13, SQLite, anyio, httpx, asyncio

---

### Task 1: N+1 Query Fix — `_load_pairs_batch()`

**Files:**
- Modify: `src/ainrf/terminal/sessions.py:422-471`

- [ ] **Step 1: Add `_load_pairs_batch()` method**

Insert after `_load_pair()` method (around line 370), before `list_session_pairs()`:

```python
    def _load_pairs_batch(self, binding_ids: list[str]) -> dict[str, UserSessionPair]:
        """Batch load pairs for multiple binding IDs in a single query."""
        result: dict[str, UserSessionPair] = {}
        if not binding_ids:
            return result
        with self._connect() as conn:
            placeholders = ','.join('?' * len(binding_ids))
            rows = conn.execute(
                f"SELECT * FROM user_session_pairs WHERE binding_id IN ({placeholders})",
                binding_ids,
            ).fetchall()
            for row in rows:
                row_dict = dict(row)
                pair = _row_to_user_session_pair(row_dict)
                result[pair.binding_id] = pair
        return result
```

- [ ] **Step 2: Refactor `list_session_pairs()` to use batch load**

Replace the loop body (lines 431-446):

```python
        binding_ids = [b.binding_id for b in bindings]
        pairs_map = self._load_pairs_batch(binding_ids)
        items: list[
            tuple[UserEnvironmentBinding, UserSessionPair, EnvironmentRegistryEntry | None]
        ] = []
        for binding in bindings:
            pair = pairs_map.get(binding.binding_id)
            if pair is None:
                continue
            environment: EnvironmentRegistryEntry | None
            try:
                environment = self._environment_service.get_environment(binding.environment_id)
            except EnvironmentNotFoundError:
                environment = None
            else:
                pair = self._refresh_pair(binding, environment, pair)
            items.append((binding, pair, environment))
        return items
```

- [ ] **Step 3: Refactor `reconcile()` to use batch load**

Replace the loop body (lines 448-471):

```python
    def reconcile(self) -> None:
        self.initialize()
        bindings = self._list_bindings()
        binding_ids = [b.binding_id for b in bindings]
        pairs_map = self._load_pairs_batch(binding_ids)
        for binding in bindings:
            pair = pairs_map.get(binding.binding_id)
            if pair is None:
                continue
            try:
                environment = self._environment_service.get_environment(binding.environment_id)
            except EnvironmentNotFoundError:
                reconcile_time = utc_now()
                self._store_pair(
                    replace(
                        pair,
                        personal_status=TerminalSessionStatus.IDLE,
                        agent_status=TerminalSessionStatus.IDLE,
                        personal_closed_at=reconcile_time,
                        last_verified_at=reconcile_time,
                        updated_at=reconcile_time,
                        detail="Environment not found during terminal reconcile",
                    )
                )
                continue
            self._refresh_pair(binding, environment, pair)
```

- [ ] **Step 4: Verify — run terminal tests**

```bash
uv run pytest tests/test_api_terminal.py tests/test_terminal_sessions.py -v -q
```

Expected: all terminal tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/ainrf/terminal/sessions.py
git commit -m "perf: add _load_pairs_batch to eliminate N+1 queries in terminal session manager"
```

---

### Task 2: File Service — Thread Offloading

**Files:**
- Modify: `src/ainrf/files/service.py:238-250`

- [ ] **Step 1: Replace `_read_local()` with thread-offloaded version**

```python
    async def _read_local(self, path: str) -> FileContent:
        from anyio import to_thread

        target = Path(path)

        def _check() -> tuple[bool, bool]:
            return (target.exists(), target.is_dir())

        exists, is_dir = await to_thread.run_sync(_check)
        if not exists:
            raise PathNotFoundError(f"File not found: {path}")
        if is_dir:
            raise PathNotFoundError(f"Path is a directory: {path}")

        stat = await to_thread.run_sync(target.stat)
        if stat.st_size > self._max_file_size:
            raise FileTooLargeError(
                f"File exceeds {self._max_file_size // 1_048_576} MB limit"
            )

        data = await to_thread.run_sync(target.read_bytes)
        return self._build_file_content(path, data)
```

- [ ] **Step 2: Run file-related tests**

```bash
uv run pytest tests/api/test_files_routes.py -v -q
```

Expected: tests pass (except pre-existing `test_read_file_too_large` failure).

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/files/service.py
git commit -m "perf: offload file read I/O to thread pool in files service"
```

---

### Task 3: Monitor Collector — Meminfo Thread Offloading

**Files:**
- Modify: `src/ainrf/monitor/collectors.py:104-107,166-183`

- [ ] **Step 1: Split `_read_meminfo()` into async wrapper + sync impl**

Replace the existing `_read_meminfo()` method (lines 166-183) with:

```python
    async def _read_meminfo_async(self) -> MemoryInfo:
        from anyio import to_thread
        return await to_thread.run_sync(self._read_meminfo)

    def _read_meminfo(self) -> MemoryInfo:
        try:
            with open("/proc/meminfo") as f:
                content = f.read()
            total_kb = 0
            available_kb = 0
            for line in content.split("\n"):
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
            used_kb = total_kb - available_kb
            total_mb = total_kb // 1024
            used_mb = used_kb // 1024
            percent = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
            return MemoryInfo(used_mb=used_mb, total_mb=total_mb, percent=percent)
        except Exception:
            return MemoryInfo(used_mb=0, total_mb=0, percent=0.0)
```

- [ ] **Step 2: Update `collect()` to avoid sync call**

Replace line 107 (`cpu, memory = self._extract_system_stats(processes)`) with:

```python
        cpu, _old_memory = self._extract_system_stats(processes)
        memory = await self._read_meminfo_async()
```

- [ ] **Step 3: Run monitor tests**

```bash
uv run pytest tests/test_monitor_process_tree.py -v -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/monitor/collectors.py
git commit -m "perf: offload meminfo file read to thread pool in resource monitor"
```

---

### Task 4: Server Health Check — Async

**Files:**
- Modify: `src/ainrf/server.py:61,83-95`

- [ ] **Step 1: Add imports and `_wait_until_healthy_async()`**

Add `import asyncio` to server.py imports, then replace `_wait_until_healthy()` with two versions:

```python
async def _wait_until_healthy_async(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{host}:{port}/health"
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(url, timeout=1.0)
                if resp.status_code in {200, 503}:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    return False


def _wait_until_healthy(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
    """Deprecated: prefer _wait_until_healthy_async. Kept for sync callers."""
    import anyio
    return anyio.run(_wait_until_healthy_async, host, port, timeout_seconds)
```

- [ ] **Step 2: Update `start_server_daemon()` call**

Line 61: `if _wait_until_healthy(host, port):` stays unchanged (the sync wrapper handles the transition).

- [ ] **Step 3: Run server-related tests**

```bash
uv run pytest tests/test_cli.py -v -q
```

Expected: all server tests pass (one pre-existing failure in `test_serve_rejects_malformed_config`).

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/server.py
git commit -m "perf: replace blocking health check with async version using httpx.AsyncClient"
```

---

### Task 5: Integration Verification

- [ ] **Step 1: Full backend test suite**

```bash
uv run pytest tests/ -q --tb=no \
  --deselect tests/api/test_files_routes.py::test_read_file_too_large \
  --deselect tests/test_cli.py::test_serve_rejects_malformed_config_with_validation_error
```

Expected: all tests pass.

- [ ] **Step 2: API benchmark regression**

Restart server: `kill $(cat ~/.ainrf/server.pid) && uv run ainrf serve --host 127.0.0.1 --port 8000 --state-root ~/.ainrf &`

Then:

```bash
sleep 3
AINRF_PERF_USER=admin AINRF_PERF_PASS=admin123 uv run pytest scripts/perf/backend/benchmark_api.py \
  --benchmark-only --benchmark-min-rounds=10 --benchmark-max-time=0.5 \
  --benchmark-json=.cache/perf-report/$(date +%Y-%m-%d)/api-benchmark.json \
  --benchmark-columns=median,mean,ops -q
```

Expected: median latencies comparable to or better than baseline (login ~350ms, create_task ~18ms, list_tasks ~3ms).

- [ ] **Step 3: Commit worklog**

```bash
git add docs/LLM-Working/worklog/2026-05-20.md
git commit -m "chore: update worklog with N+1/sync I/O fix verification"
```

---

## Verification Checklist

1. `uv run pytest tests/ -q` — all tests pass (skipping 2 pre-existing failures)
2. `cd frontend && node_modules/.bin/tsc -b` — frontend type check passes
3. API benchmark regression — no latency regressions
4. Server starts successfully with async health check
