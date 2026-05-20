# Database Index Optimization Design

## 目标

基于性能审计工具链产出的索引分析报告，对 scholar-agent 项目 4 个 SQLite 数据库补齐 24 个缺失索引，消除全表扫描，降低 API 查询延迟。

## 范围

### 高优先级（每次请求都命中）

| 表 | 索引列 | 覆盖查询 |
|-----|--------|----------|
| `task_harness_tasks` | `(project_id, status)` | 项目任务列表、任务创建去重 |
| `task_harness_tasks` | `session_id` | session 关联任务查询 |
| `task_harness_edges` | `project_id` | 项目边列表 |
| `task_harness_edges` | `source_task_id` | 边创建查重 |
| `task_harness_edges` | `target_task_id` | 边创建查重 |
| `refresh_tokens` | `user_id` | token 刷新查找 |
| `users` | `status` | 用户列表过滤 |
| `task_sessions` | `project_id` | session 列表 |
| `task_sessions` | `status` | session 状态过滤 |

### 中优先级（特定场景命中）

| 表 | 索引列 |
|-----|--------|
| `task_harness_tasks` | `environment_id`, `workspace_id`, `owner_user_id`, `created_at` |
| `task_harness_output_events` | `kind` |
| `task_sessions` | `created_at` |
| `task_attempts` | `parent_attempt_id`, `status` |
| `refresh_tokens` | `expires_at` |

## 实现方式

所有索引通过 `CREATE INDEX IF NOT EXISTS` 添加，放入对应 service 的 `initialize()` 方法中，与表创建语句同位置。服务每次启动时自动补齐缺失索引，无需手动迁移。

### `src/ainrf/auth/service.py` — `AuthService.initialize()`

在 `CREATE TABLE` 语句之后追加：

```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)")
```

### `src/ainrf/task_harness/service.py` — `TaskHarnessService.initialize()`

```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON task_harness_tasks(project_id, status)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON task_harness_tasks(session_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_environment_id ON task_harness_tasks(environment_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_workspace_id ON task_harness_tasks(workspace_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner_user_id ON task_harness_tasks(owner_user_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON task_harness_tasks(created_at)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_project_id ON task_harness_edges(project_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON task_harness_edges(source_task_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON task_harness_edges(target_task_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_output_events_kind ON task_harness_output_events(kind)")
```

### `src/ainrf/sessions/service.py` — `SessionService.initialize()`

```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project_status ON task_sessions(project_id, status)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON task_sessions(created_at)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_parent ON task_attempts(parent_attempt_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_status ON task_attempts(status)")
```

### 关键设计决策

- `task_harness_tasks(project_id, status)` 使用**复合索引**而非两个单列索引。核心查询模式是 `WHERE project_id = ? AND status != 'archived'`，复合索引比两个独立索引更高效，因为 SQLite 只需一次 B-tree 查找即可定位所有匹配行。
- 其余列使用单列索引，因为查询模式通常是单列过滤（如 `WHERE session_id = ?`、`WHERE environment_id = ?`），复合索引不会带来额外收益。
- 使用 `IF NOT EXISTS` 保证幂等性，多次运行 `initialize()` 不会报错。
- 索引名称使用 `idx_<table>_<column>` 或 `idx_<table>_<col1>_<col2>` 命名规范，便于后续 `analyze_db.py` 工具识别。

## 验证

1. **索引审计回归**：`uv run python scripts/perf/run-all.py --target db`，确认 24 条缺失索引全部消除
2. **API 基准对比**（需 server 运行）：`uv run python scripts/perf/run-all.py --target backend`，对比索引添加前后的 p50/p95 延迟
3. **测试套件**：`uv run pytest tests/ -q` 全部通过，索引创建不引入 sqlite 锁冲突
4. **前端静态检查**：`cd frontend && node_modules/.bin/tsc -b` 通过
