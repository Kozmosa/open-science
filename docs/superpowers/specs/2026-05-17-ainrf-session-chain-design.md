# AINRF Session Chain — Design Spec

Date: 2026-05-17 | Session: `ainrf-h2` | Status: draft

## Motivation

AINRF 当前缺乏对 "同一次研究任务的多次尝试" 的建模。Task 之间可以通过 Task Edge 做 DAG 编排，但没有原生的 session/attempt 概念。从 humanize2 借鉴 Session Chain 模式，为后续的 Token 用量追踪和 Timeline 可视化提供基础设施。

## Data Model

新增两张表，存入 task_harness SQLite DB，不影响现有 tasks 表。

### task_sessions

```sql
CREATE TABLE IF NOT EXISTS task_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | completed | archived
    task_count INTEGER NOT NULL DEFAULT 0,
    total_duration_ms INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### task_attempts

```sql
CREATE TABLE IF NOT EXISTS task_attempts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES task_sessions(id),
    task_id TEXT,                              -- nullable: 关联现有 Task
    parent_attempt_id TEXT,                    -- 自引用: 形成 attempt chain
    attempt_seq INTEGER NOT NULL,              -- 1, 2, 3...
    intervention_reason TEXT,                  -- 中断/继续的原因
    status TEXT NOT NULL DEFAULT 'running',    -- running | completed | failed | interrupted
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    token_usage_json TEXT,                     -- {"input": N, "output": N, "cache": N, "reasoning": N, "cost_usd": N}
    created_at TEXT NOT NULL
);
```

### 关键设计决策

- **TaskAttempt 独立于 Task**：不改 tasks 表，task_id nullable，session 操作可以不创建 Task
- **Session 预聚合字段**：task_count / total_duration / total_cost 存表，避免每次列表查询都 JOIN
- **parent_attempt_id**：自引用形成 attempt chain，供 Timeline 渲染和中断历史追溯
- **token_usage_json**：SQLite JSON 列，为 Token Track 阶段预留

### Session 生命周期

```
Create Session → Attempt #1 (running → completed/failed)
  → Attempt #2 (parent=#1, 用户中断后继续)
  → Attempt #3 (parent=#2)
  → Session completed/archived
```

## API Design

### 新增 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions` | 列表，支持 `?project_id=&status=` 筛选 |
| POST | `/sessions` | 创建 session（title, project_id） |
| GET | `/sessions/{id}` | Session 详情 + attempts 列表 + 聚合统计 |
| PATCH | `/sessions/{id}` | 更新 title / status |
| DELETE | `/sessions/{id}` | Archive session（软删除） |
| GET | `/sessions/{id}/attempts` | Session 下所有 attempts（按 seq 排序） |

### 现有 Task API 扩展

- `POST /tasks` — 新增可选字段 `session_id`
- `GET /tasks/{id}` — response 新增 `session_id`, `attempt_seq`

### TaskAttempt 自动维护

- task 从 QUEUED → STARTING 时，自动创建 TaskAttempt
- task 完成/失败时，自动更新 attempt 的 status + duration + token_usage
- task 被 cancel 后 resume 或收到 prompt 后，在同 session 下创建新 attempt（parent=上一个）
- Session 聚合字段在每次 attempt 完成后自动 recalculate

## Frontend Design

### SessionsPage

- 路由 `/sessions`
- 布局: `PageShell > SplitPane(SessionList | SessionDetail)`
- 复用组件: PageShell, SplitPane, SectionStack, StatusDot, Badge

### AttemptChain 组件

- 垂直时间线展示 session 下所有 attempts
- 每个 attempt 卡片: seq 编号、status badge、关联 task（可点击跳转）、duration、token 概览、intervention_reason
- 连接线 + 圆点标识 attempt 先后顺序

### 与 TasksPage 关联

- TaskDetail 中显示所属 session 链接
- TaskCreateForm 增加可选的 session_id 选择器

## Backward Compatibility

- session_id = null 的 task 不受影响
- Task API session_id 为可选字段
- 无 session 的 task 不触发 TaskAttempt 创建
- 新表独立于现有表，migration 不修改现有表
- 前端仅新增路由，现有 8 个路由不变

## Implementation Order

1. DB Migration — task_sessions + task_attempts 表
2. Backend — SessionService + API routes + Pydantic schemas
3. Task Harness 集成 — auto-create/update TaskAttempt
4. Frontend — SessionsPage + AttemptChain + 路由注册
5. 关联 — TasksPage session 链接 + TaskCreateForm session 选择器
6. Follow-up — Token Track → Timeline（依赖 Session Chain）

## Testing

### Backend (pytest)
- Session CRUD 全流程
- TaskAttempt 自动创建/更新
- Session 聚合字段正确性
- Attempt chain parent 追溯查询
- session_id=null 时 task 行为不变
- DB migration 幂等性

### Frontend (Vitest)
- SessionsPage 渲染（空态/有数据）
- SessionList 筛选与搜索
- AttemptChain 不同状态的渲染
- Session ↔ Task 双向链接跳转
- TaskCreateForm session_id 选择器
- i18n 覆盖（中英文）

## Visual Companion

Brainstorming 过程中的可视化页面保存在:
`docs/superpowers/specs/2026-05-17-ainrf-h2-brainstorm/visual-companion/`
