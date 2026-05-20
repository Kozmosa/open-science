# N+1 Query and Sync I/O Optimization Design

## 目标

消除代码审计发现的 6 个性能瓶颈：2 个 N+1 查询模式、3 个同步阻塞 I/O 在 async 路径、1 个阻塞健康检查。

## 范围

### N+1 查询修复

| 位置 | 方法 | 问题 | 修复 |
|------|------|------|------|
| `terminal/sessions.py:434-446` | `list_session_pairs()` | 逐对调用 `_load_pair()`，每对开辟新 sqlite 连接 | 新增 `_load_pairs_batch()` 批量查询 |
| `terminal/sessions.py:448-471` | `reconcile()` | 同上模式 | 复用 `_load_pairs_batch()` |

### 同步 I/O 移至线程池

| 位置 | 方法 | 阻塞调用 | 修复 |
|------|------|----------|------|
| `files/service.py:238-250` | `_read_local()` | `target.read_bytes()`, `target.stat()`, `target.exists()` | `to_thread.run_sync` 包裹 |
| `monitor/collectors.py:166-183` | `_read_meminfo()` | `open("/proc/meminfo")` + `f.read()` | 拆为 sync + async wrapper |
| `server.py:83-95` | `_wait_until_healthy()` | `httpx.get()`, `time.sleep(0.2)` | 改为 `httpx.AsyncClient` + `asyncio.sleep` |

## 实现

### 1. `src/ainrf/terminal/sessions.py` — `_load_pairs_batch()`

在 `SessionManager` 类中新增批量加载方法：

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

修改 `list_session_pairs()`：

```python
def list_session_pairs(self, app_user_id, environment_id=None):
    self.initialize()
    bindings = [b for b in self._list_bindings() if b.user_id == app_user_id]
    if environment_id is not None:
        bindings = [b for b in bindings if b.environment_id == environment_id]

    binding_ids = [b.binding_id for b in bindings]
    pairs_map = self._load_pairs_batch(binding_ids)

    items = []
    for binding in bindings:
        pair = pairs_map.get(binding.binding_id)
        if pair is None:
            continue
        try:
            environment = self._environment_service.get_environment(binding.environment_id)
        except EnvironmentNotFoundError:
            environment = None
        else:
            pair = self._refresh_pair(binding, environment, pair)
        items.append((binding, pair, environment))
    return items
```

修改 `reconcile()`：

```python
def reconcile(self):
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
            pair = replace(pair, personal_status=TerminalSessionStatus.IDLE,
                           agent_status=TerminalSessionStatus.IDLE,
                           personal_closed_at=utc_now(),
                           last_verified_at=utc_now(), updated_at=utc_now(),
                           detail="Environment not found during terminal reconcile")
            self._store_pair(pair)
            continue
        self._refresh_pair(binding, environment, pair)
```

### 2. `src/ainrf/files/service.py` — 文件 I/O 移至线程池

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

### 3. `src/ainrf/monitor/collectors.py` — meminfo 读至线程池

```python
async def _read_meminfo(self) -> MemoryInfo:
    from anyio import to_thread
    return await to_thread.run_sync(self._read_meminfo_sync)

@staticmethod
def _read_meminfo_sync() -> MemoryInfo:
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

调用处 `collect()` 改为直接 `await self._read_meminfo()`（绕过 `_extract_system_stats` 中同步调用）：

```python
def _extract_system_stats(self, processes: list[RawProcess]) -> tuple[CpuInfo, MemoryInfo]:
    ...  # _read_meminfo() 改为从 collect() 中直接 await，不再在此同步调用
```

### 4. `src/ainrf/server.py` — 异步健康检查

```python
import asyncio

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
```

`start_server_daemon()` 中调用改为：

```python
ok = anyio.run(_wait_until_healthy_async, host, port)
```

保留原同步版本 `_wait_until_healthy()` 给非 async 场景（如有），并在 docstring 注明 `deprecated: prefer _wait_until_healthy_async`。

## 验证

1. **后端测试**：`uv run pytest tests/ -q` 全量通过
2. **前端类型检查**：`cd frontend && node_modules/.bin/tsc -b`
3. **API 基准回归**：server 重启后 `uv run python scripts/perf/run-all.py --target backend`，确认中等延迟无退化
4. **手动验证**：
   - `POST /files/read` 读取大文件不阻塞其他请求
   - 终端 session 列表加载时间缩短
   - 服务启动健康检查正常
