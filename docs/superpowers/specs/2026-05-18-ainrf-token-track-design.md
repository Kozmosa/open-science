# AINRF Token Track — Design Spec

Date: 2026-05-18 | Session: `ainrf-h2` | Status: draft | Depends on: Session Chain

## Motivation

Session Chain 已就位（task_sessions + task_attempts），但 token 数据未被捕获——`task_attempts.token_usage_json` 永远为 NULL，`task_sessions.total_cost_usd` 永远为 0。Agent SDK engine 的 `ResultMessage` 携带 `usage`、`model_usage`、`total_cost_usd`，但当前 `_convert_sdk_message` 丢弃了它们。Claude Code CLI 的 `~/.claude/usage-data/session-meta/` 包含 `input_tokens` + `output_tokens`，但从未被读取。

目标：统一地从两个 engine 提取 token 数据，写入 Session Chain，前端可视化展示。

## Data Flow

```
AgentSdkEngine                        ClaudeCodeEngine
ResultMessage.usage                   session-meta/<uuid>.json
ResultMessage.model_usage             (post-exit polling, 30s timeout)
ResultMessage.total_cost_usd
        |                                      |
        v                                      v
EngineEvent(token_usage=...)     EngineEvent(token_usage=...)
        |                                      |
        +------------- emit() -----------------+
                          |
                    captured_token_usage (local var)
                    + TaskOutputKind.TOKEN events (real-time)
                          |
                          v
              session_service.complete_attempt(
                token_usage_json=json.dumps(token_usage))
                          |
                          v
              _recalc_session: json_extract($.total.cost_usd) → total_cost_usd
```

## EngineEvent Extension (base.py)

```python
@dataclass(slots=True)
class EngineEvent:
    event_type: Literal["message", "thinking", "tool_call", "tool_result", "status", "system", "error", "token"]
    subtype: str | None
    payload: str
    token_usage: dict[str, Any] | None = None  # NEW
```

event_type 新增 `"token"` 值，用于 per-turn token 快照的实时流。

## TaskOutputKind Extension (models.py)

```python
class TaskOutputKind(StrEnum):
    ...
    TOKEN = "token"  # NEW
```

## token_usage_json Structure

```json
{
  "total": {
    "input_tokens": 48200,
    "output_tokens": 8150,
    "cache_creation_input_tokens": 12000,
    "cache_read_input_tokens": 8500,
    "cost_usd": 3.42
  },
  "by_model": {
    "claude-opus-4-7": {
      "input_tokens": 32000,
      "output_tokens": 6100,
      "cache_creation_input_tokens": 8000,
      "cache_read_input_tokens": 5000,
      "cost_usd": 2.85
    }
  },
  "source": "agent-sdk"
}
```

- Agent SDK: `source="agent-sdk"`, 完整的 total + by_model + cost_usd
- Claude Code: `source="claude-session-meta"`, 仅 total.input_tokens + total.output_tokens

## Engine Changes

### AgentSdkEngine (agent_sdk.py)

在 `_convert_sdk_message` 处理 `ResultMessage` 时提取：
- `sdk_msg.usage` → token_usage["total"]
- `sdk_msg.model_usage` → token_usage["by_model"]
- `sdk_msg.total_cost_usd` → token_usage["total"]["cost_usd"]

每个 `AssistantMessage.usage` 作为 per-turn token 快照 → `EngineEvent("token", None, "", token_usage=...)` 实时发射。

### ClaudeCodeEngine (claude_code.py)

子进程退出后：
1. 记录 task 启动时间
2. 轮询 `~/.claude/usage-data/session-meta/` 目录（每秒一次，最多 30 秒）
3. 按启动时间 ± 5 秒窗口匹配 `start_time` 字段
4. 提取 `input_tokens` + `output_tokens`
5. 构建 token_usage dict → 通过 EngineEvent 发射
6. 超时未匹配 → token_usage=None，静默跳过

## Task Harness Integration (service.py)

### SessionService 注入

```python
class TaskHarnessService:
    def __init__(self, *, state_root, ..., session_service: SessionService | None = None):
        self._session_service = session_service
```

### emit 闭包捕获 token_usage

在 `_run_task` 的 emit 闭包中：
- `event.event_type == "token"` → 写入 `TaskOutputKind.TOKEN` output event
- `event.subtype == "task_completed"` → 保存 token_usage 到局部变量

### engine.start() 返回后写入

```python
if self._session_service and task_session_id and captured_token_usage:
    try:
        attempts = self._session_service.list_attempts(task_session_id)
        latest = attempts[-1] if attempts else None
        if latest and latest.task_id == task_id:
            self._session_service.complete_attempt(
                latest.id,
                status="completed",
                duration_ms=...,
                token_usage_json=json.dumps(captured_token_usage),
            )
    except Exception:
        logger.warning("failed to update session attempt token", exc_info=True)
```

### app.py wiring

```python
session_service = SessionService(state_root=api_config.state_root)
app.state.session_service = session_service

task_harness_service = TaskHarnessService(
    ...,
    session_service=session_service,
)
```

## _recalc_session Extension (sessions/service.py)

在聚合查询中添加 cost：

```sql
SELECT COUNT(*) AS cnt,
       COALESCE(SUM(duration_ms), 0) AS dur,
       COALESCE(SUM(CAST(json_extract(token_usage_json, '$.total.cost_usd') AS REAL)), 0.0) AS total_cost
FROM task_attempts
WHERE session_id = ? AND duration_ms IS NOT NULL
```

UPDATE 语句同步更新 `total_cost_usd = ?`。

## Frontend Changes

### TokenFlowBar Component (NEW)

- 横向分色 bar：input(blue) / cache(green) / output(yellow) / reasoning(gray)
- 宽度按 token 占比计算
- 图例标注各类型 token 数量和百分比
- 空态：无 token 数据时不渲染
- Claude Code 态：仅显示 input/output 两色

### AttemptChain Integration

- 每个 attempt 卡片底部显示 TokenFlowBar（替换当前 "Token data" 文字）
- 有 `token_usage_json` 时自动渲染

### SessionDetail Upgrade

- Stats bar 显示实际 `total_cost_usd`（当前始终为 $0.00）
- 新增 `total_tokens` 汇总

### Per-Model Breakdown (AttemptChain 卡片内)

- 可折叠 `<details>` 区域
- 每个 model 一行：model name + cost + mini flow bar

### Per-Project Cost Aggregation

新 API: `GET /projects/{project_id}/cost-summary`

```json
{
  "project_id": "proj_1",
  "total_cost_usd": 23.45,
  "total_tokens": 520000,
  "session_count": 5,
  "by_model": {
    "claude-opus-4-7": {"cost_usd": 18.20, "tokens": 380000}
  }
}
```

前端在 ProjectsPage 或 project 卡片中展示。

### TypeScript Types

```typescript
export interface TokenUsage {
  total: {
    input_tokens: number;
    output_tokens: number;
    cache_creation_input_tokens?: number;
    cache_read_input_tokens?: number;
    cost_usd?: number;
  };
  by_model?: Record<string, {
    input_tokens: number;
    output_tokens: number;
    cost_usd?: number;
  }>;
  source: 'agent-sdk' | 'claude-session-meta';
}
```

## Implementation Order

1. EngineEvent 扩展 + TaskOutputKind.TOKEN + AgentSdkEngine token 提取
2. Task Harness 集成: SessionService 注入 + emit 捕获 + complete_attempt 写入
3. ClaudeCodeEngine session-meta 轮询提取
4. _recalc_session cost 聚合 + Project cost-summary API
5. 前端: TokenFlowBar + AttemptChain 集成 + SessionDetail 升级
6. 前端: Per-Model Breakdown + Per-Project Cost + i18n

## Testing

### Backend (pytest)
- EngineEvent.token_usage 序列化/反序列化
- AgentSdkEngine ResultMessage token 提取
- ClaudeCodeEngine session-meta 轮询（含超时处理）
- TaskOutputKind.TOKEN 事件正确写入 output_events
- _run_task 中 token_usage 捕获 → complete_attempt 调用链
- _recalc_session cost 聚合（含 NULL token_usage_json）
- SessionService 注入为 None 时向后兼容
- GET /projects/{id}/cost-summary

### Frontend (Vitest)
- TokenFlowBar 渲染（4 色比例）、空态、Claude Code 模式
- SessionDetail total_cost_usd + total_tokens 展示
- Per-Model Breakdown 展开/折叠
- AttemptChain 集成 TokenFlowBar

## Visual Companion

Brainstorming 可视化页面: `docs/superpowers/specs/2026-05-18-ainrf-token-track/visual-companion/`
