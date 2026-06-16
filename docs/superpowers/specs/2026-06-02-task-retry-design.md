# Task Retry Feature Design

> Date: 2026-06-02  
> Author: AI Assistant (Kiro)  
> Status: Draft for Review

## Overview

Add a retry feature for failed TaskHarness tasks, allowing users to re-run a task with the same configuration. When a user clicks "Retry", the system automatically archives the old failed task, creates a new task with identical configuration, and establishes a task edge to track the retry relationship.

## Motivation

**Problem:** When a research task fails due to transient issues (network timeouts, temporary resource unavailability, execution engine errors), users currently have to:
1. Manually inspect the failed task configuration
2. Navigate to "New Task" form
3. Re-enter all parameters (workspace, environment, prompt, agent profile)
4. Manually archive or delete the old failed task

This is tedious and error-prone.

**Goal:** Provide a one-click "Retry" action that:
- Preserves all original task configuration
- Automatically archives the failed task
- Creates a new task ready to run
- Maintains audit trail via task edges

## Architecture

### Component Overview

```
┌─────────────┐
│   Frontend  │
│  (Retry UI) │
└──────┬──────┘
       │ POST /tasks/{id}/retry
       ▼
┌─────────────────┐
│  API Route      │
│  /tasks routes  │
└──────┬──────────┘
       │
       ▼
┌─────────────────────────┐
│ TaskHarnessService      │
│  .retry_task()          │
│    ├─ validate status   │
│    ├─ archive old task  │
│    ├─ clone config      │
│    ├─ create new task   │
│    └─ create edge       │
└─────────────────────────┘
```

### Data Model

**No new tables needed.** Reuse existing structures:

1. **Task Edges** - track retry relationships
   - `source_task_id`: the failed/cancelled task
   - `target_task_id`: the new retry task
   - `edge_type` (optional future enhancement): "retry" | "dependency" | "manual"

2. **Archived Tasks** - old tasks are marked archived
   - `archived_at`: timestamp when archived
   - Default queries filter `WHERE archived_at IS NULL`

### Task Status Flow

```
User creates task
    ↓
  QUEUED → STARTING → RUNNING → {SUCCEEDED | FAILED | CANCELLED}
                                       ↓
                                  User clicks Retry
                                       ↓
                             Old task: archived_at = now()
                                       ↓
                             New task: QUEUED (fresh start)
                                       ↓
                             Edge created: old → new
```

## API Design

### Endpoint

**`POST /tasks/{task_id}/retry`**

**Request Body (all optional - allows modification before retry):**

```json
{
  "task_input": "optional: override the original prompt",
  "environment_id": "optional: use a different environment",
  "research_agent_profile": {
    "model": "optional: change model",
    "max_turns": 50
  }
}
```

**Response (200 OK):**

```json
{
  "new_task": {
    "task_id": "uuid-new",
    "status": "queued",
    "title": "Original Task Title",
    ...
  },
  "archived_task_id": "uuid-old",
  "edge_id": "uuid-edge"
}
```

**Error Responses:**

- `404 Not Found`: Original task does not exist
- `409 Conflict`: Task status is not FAILED or CANCELLED
- `404 Not Found`: Referenced workspace/environment no longer exists
- `403 Forbidden`: User does not own the task (non-admin)

### Backend Implementation

**`TaskHarnessService.retry_task()` pseudocode:**

```python
def retry_task(
    self,
    task_id: str,
    *,
    task_input: str | None = None,
    environment_id: str | None = None,
    research_agent_profile: dict | None = None,
    owner_user_id: str
) -> dict[str, Any]:
    """
    Retry a failed or cancelled task.
    
    Steps:
    1. Load and validate the original task
    2. Check task status (must be FAILED or CANCELLED)
    3. Archive the original task
    4. Clone configuration (with optional overrides)
    5. Create new task via existing create_task()
    6. Create task edge: old_task → new_task
    7. Return new task details
    """
    
    # 1. Load original task
    old_task = self.get_task(task_id)
    
    # 2. Validate status
    if old_task.status not in {TaskHarnessStatus.FAILED, TaskHarnessStatus.CANCELLED}:
        raise TaskHarnessError(
            "Only failed or cancelled tasks can be retried. "
            f"Current status: {old_task.status}"
        )
    
    # 3. Archive old task
    self.archive_task(task_id)
    
    # 4. Clone configuration (apply overrides)
    new_task = self.create_task(
        project_id=old_task.project_id,
        workspace_id=old_task.workspace_summary.workspace_id,
        environment_id=environment_id or old_task.environment_summary.environment_id,
        task_profile=old_task.task_profile,
        task_input=task_input or old_task.binding.task_input,
        title=old_task.title,  # Keep original title (or add "[Retry]" prefix?)
        execution_engine=old_task.execution_engine,
        auto_connect=False,
        session_id=None,  # New task gets new session
        owner_user_id=owner_user_id,
        research_agent_profile=(
            research_agent_profile 
            if research_agent_profile is not None 
            else asdict(old_task.research_agent_profile)
        ),
        task_configuration=asdict(old_task.task_configuration),
    )
    
    # 5. Create retry edge
    edge = self.create_task_edge(
        project_id=old_task.project_id,
        source_task_id=task_id,
        target_task_id=new_task.task_id,
    )
    
    return {
        "new_task": new_task,
        "archived_task_id": task_id,
        "edge_id": edge.edge_id,
    }
```

**API Route (`src/ainrf/api/routes/tasks.py`):**

```python
@router.post("/{task_id}/retry", response_model=TaskRetryResponse)
async def retry_task(
    task_id: str,
    payload: TaskRetryRequest,
    request: Request
) -> TaskRetryResponse:
    """Retry a failed or cancelled task."""
    user = get_current_user(request)
    service = _get_task_harness_service(request)
    
    try:
        # Check ownership
        old_task = service.get_task(task_id)
        if not check_resource_owner(user, old_task.owner_user_id):
            raise HTTPException(status_code=403, detail="Permission denied")
        
        # Retry
        result = service.retry_task(
            task_id=task_id,
            task_input=payload.task_input,
            environment_id=payload.environment_id,
            research_agent_profile=payload.research_agent_profile.model_dump()
            if payload.research_agent_profile is not None
            else None,
            owner_user_id=user["id"],
        )
        
        return TaskRetryResponse.model_validate(result)
    except Exception as exc:
        raise _translate_task_error(exc) from exc
```

## Frontend Design

### UI Components

**1. Task Card/List Item (FAILED/CANCELLED tasks only)**

Add a "Retry" button alongside existing "Cancel" and "Archive" actions:

```
┌────────────────────────────────────┐
│ Task: Data preprocessing pipeline  │
│ Status: Failed                     │
│ Error: Process exited with code 1 │
│                                    │
│ [Archive] [Retry]                  │
└────────────────────────────────────┘
```

**Visual states:**
- Disabled when task is RUNNING/QUEUED/SUCCEEDED
- Primary button style for FAILED/CANCELLED
- Shows loading spinner during retry API call

**2. Task Detail Page**

Display retry relationship in task summary section:

```
┌─────────────────────────────────────┐
│ Task Summary                        │
│ ─────────────────────────────────   │
│ Status: Running                     │
│ Created: 2026-06-02 10:30           │
│                                     │
│ Relationships:                      │
│ ↳ Retried from: Task #abc123 ⓘ     │
│   (Click to view original)          │
└─────────────────────────────────────┘
```

For archived tasks, show retry successors:

```
┌─────────────────────────────────────┐
│ Task Summary                        │
│ ─────────────────────────────────   │
│ Status: Failed (archived)           │
│                                     │
│ Relationships:                      │
│ ↳ Retried as: Task #def456 ⓘ       │
│   (Click to view retry)             │
└─────────────────────────────────────┘
```

**3. Confirmation Dialog (optional MVP feature)**

For simple retry (no config changes), skip dialog and retry immediately with a toast notification.

For advanced users, add a settings option to show confirmation:

```
┌───────────────────────────────────────┐
│ Retry Task?                           │
│                                       │
│ This will:                            │
│ • Archive the failed task             │
│ • Create a new task with same config  │
│ • Start execution immediately         │
│                                       │
│ [Cancel] [Retry]                      │
└───────────────────────────────────────┘
```

### User Flow

1. **User sees failed task in list**
   - "Retry" button is visible and enabled
   
2. **User clicks "Retry"**
   - Button shows loading spinner
   - API call: `POST /tasks/{id}/retry`
   
3. **Success response received**
   - Toast notification: "Task retried successfully"
   - Navigate to new task detail page
   - Old task disappears from default list (archived)
   
4. **Error handling**
   - Network error: Toast "Failed to retry task. Check connection."
   - 409 Conflict: Toast "Task cannot be retried (status: running)"
   - 404 Not Found: Toast "Workspace or environment no longer exists"

### i18n Implementation

**Add to `frontend/src/i18n/messages.ts`:**

```typescript
export const messages = {
  en: {
    // ... existing keys
    pages: {
      tasks: {
        actions: {
          cancel: 'Cancel',
          archive: 'Archive',
          retry: 'Retry',                           // NEW
          showArchived: 'Show archived',
        },
        retrySuccess: 'Task retried successfully',  // NEW
        retryFailed: 'Failed to retry task',        // NEW
        retryInvalidStatus: 'Task cannot be retried (status: {{status}})', // NEW
        retryMissingResource: 'Cannot retry: workspace or environment no longer exists', // NEW
        retriedFrom: 'Retried from task {{taskId}}', // NEW
        retriedAs: 'Retried as task {{taskId}}',     // NEW
      }
    }
  },
  zh: {
    // ... existing keys
    pages: {
      tasks: {
        actions: {
          cancel: '取消',
          archive: '归档',
          retry: '重试',                            // NEW
          showArchived: '显示已归档',
        },
        retrySuccess: '任务已重试',                  // NEW
        retryFailed: '重试失败',                    // NEW
        retryInvalidStatus: '任务无法重试（当前状态：{{status}}）', // NEW
        retryMissingResource: '无法重试：工作区或环境已被删除', // NEW
        retriedFrom: '重试自任务 {{taskId}}',        // NEW
        retriedAs: '已重试为任务 {{taskId}}',        // NEW
      }
    }
  }
};
```

**Usage in components:**

```tsx
import { useT } from '../../i18n';

function TaskActions({ task }: { task: TaskSummary }) {
  const t = useT();
  
  const handleRetry = async () => {
    try {
      const result = await retryTask(task.task_id);
      toast.success(t('pages.tasks.retrySuccess'));
      navigate(`/tasks/${result.new_task.task_id}`);
    } catch (error) {
      if (error.status === 409) {
        toast.error(t('pages.tasks.retryInvalidStatus', { status: task.status }));
      } else if (error.status === 404) {
        toast.error(t('pages.tasks.retryMissingResource'));
      } else {
        toast.error(t('pages.tasks.retryFailed'));
      }
    }
  };
  
  return (
    <div>
      {/* ... other actions */}
      {(task.status === 'failed' || task.status === 'cancelled') && (
        <Button onClick={handleRetry}>
          {t('pages.tasks.actions.retry')}
        </Button>
      )}
    </div>
  );
}
```

## Error Handling

### Common Failure Scenarios

**1. Workspace deleted after task creation**
- **Detection:** `WorkspaceNotFoundError` during `create_task()`
- **Response:** 404 with message "Cannot retry: workspace no longer exists"
- **UI:** Toast notification, suggest creating new task manually

**2. Environment deleted/unavailable**
- **Detection:** `EnvironmentNotFoundError` during `create_task()`
- **Response:** 404 with message "Cannot retry: environment no longer exists"
- **UI:** Toast notification, option to select different environment (future enhancement)

**3. Permission denied**
- **Detection:** `owner_user_id` mismatch (non-admin user)
- **Response:** 403 Forbidden
- **UI:** Toast "You don't have permission to retry this task"

**4. Invalid task status**
- **Detection:** Task status is RUNNING/QUEUED/SUCCEEDED
- **Response:** 409 Conflict with current status in message
- **UI:** Toast "Task cannot be retried (currently running)"

**5. Concurrent retry requests**
- **Scenario:** User clicks "Retry" twice quickly
- **Mitigation:** Disable button immediately on click, show loading state
- **Backend:** Second request will fail because task is already archived (409)

### Rollback Strategy

**If retry fails after archive:**
- Current implementation: Old task remains archived, no new task created
- Alternative (future enhancement): Un-archive old task on failure
- **Decision:** Keep simple - archived state is harmless, user can see error and manually un-archive if needed

## Testing Strategy

### Unit Tests

**Backend (`tests/test_task_harness_service.py`):**

```python
def test_retry_task_success():
    """Retry creates new task, archives old, creates edge."""
    service = TaskHarnessService(...)
    
    # Create and fail a task
    old_task = service.create_task(...)
    service._mark_task_failed(old_task.task_id)
    
    # Retry
    result = service.retry_task(old_task.task_id, owner_user_id="user-1")
    
    # Assertions
    assert result["archived_task_id"] == old_task.task_id
    assert result["new_task"].task_id != old_task.task_id
    assert result["new_task"].status == TaskHarnessStatus.QUEUED
    
    # Check old task is archived
    old_task_reloaded = service.get_task(old_task.task_id)
    assert old_task_reloaded.archived_at is not None
    
    # Check edge exists
    edges = service.list_task_edges(project_id=old_task.project_id)
    assert any(
        e.source_task_id == old_task.task_id 
        and e.target_task_id == result["new_task"].task_id
        for e in edges
    )

def test_retry_task_invalid_status():
    """Cannot retry a running task."""
    service = TaskHarnessService(...)
    task = service.create_task(...)
    # Task is QUEUED, not FAILED
    
    with pytest.raises(TaskHarnessError, match="Only failed or cancelled"):
        service.retry_task(task.task_id, owner_user_id="user-1")

def test_retry_task_not_found():
    """Cannot retry non-existent task."""
    service = TaskHarnessService(...)
    
    with pytest.raises(TaskHarnessNotFoundError):
        service.retry_task("invalid-id", owner_user_id="user-1")

def test_retry_task_preserves_config():
    """New task has same config as original."""
    service = TaskHarnessService(...)
    
    old_task = service.create_task(
        workspace_id="ws-1",
        environment_id="env-1",
        task_input="Analyze data",
        research_agent_profile={"model": "claude-sonnet-4-6"},
        ...
    )
    service._mark_task_failed(old_task.task_id)
    
    result = service.retry_task(old_task.task_id, owner_user_id="user-1")
    new_task = result["new_task"]
    
    assert new_task.workspace_summary.workspace_id == "ws-1"
    assert new_task.environment_summary.environment_id == "env-1"
    assert new_task.binding.task_input == "Analyze data"
    assert new_task.research_agent_profile.model == "claude-sonnet-4-6"

def test_retry_task_with_overrides():
    """Retry with modified config applies overrides."""
    service = TaskHarnessService(...)
    
    old_task = service.create_task(task_input="Original prompt", ...)
    service._mark_task_failed(old_task.task_id)
    
    result = service.retry_task(
        old_task.task_id,
        task_input="Modified prompt",
        owner_user_id="user-1"
    )
    
    assert result["new_task"].binding.task_input == "Modified prompt"
```

### Integration Tests

**API endpoint (`tests/test_tasks_routes.py`):**

```python
async def test_retry_task_endpoint(client, auth_token):
    """POST /tasks/{id}/retry returns new task."""
    # Create and fail a task
    create_response = await client.post(
        "/tasks",
        json={...},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    task_id = create_response.json()["task_id"]
    
    # Mark as failed (test helper)
    await mark_task_as_failed(task_id)
    
    # Retry
    retry_response = await client.post(
        f"/tasks/{task_id}/retry",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    
    assert retry_response.status_code == 200
    data = retry_response.json()
    assert data["archived_task_id"] == task_id
    assert data["new_task"]["task_id"] != task_id
    assert data["new_task"]["status"] == "queued"

async def test_retry_task_permission_denied(client, auth_token_user2):
    """Cannot retry another user's task."""
    # User 1 creates task
    task_id = await create_task_as_user1()
    await mark_task_as_failed(task_id)
    
    # User 2 tries to retry
    response = await client.post(
        f"/tasks/{task_id}/retry",
        headers={"Authorization": f"Bearer {auth_token_user2}"}
    )
    
    assert response.status_code == 403
```

### E2E Tests (Playwright)

```typescript
test('retry failed task', async ({ page }) => {
  // Setup: Create and fail a task
  await page.goto('/tasks');
  await page.click('text=New task');
  await fillTaskForm(page, { prompt: 'Test task' });
  await page.click('text=Create task');
  
  // Wait for task to fail (or simulate failure)
  await page.waitForSelector('text=Failed');
  
  // Click retry
  await page.click('button:has-text("Retry")');
  
  // Should navigate to new task
  await page.waitForURL(/\/tasks\/[a-f0-9-]+$/);
  await expect(page.locator('text=Queued')).toBeVisible();
  
  // Should show "Retried from" relationship
  await expect(page.locator('text=Retried from task')).toBeVisible();
  
  // Old task should be archived (not in default list)
  await page.goto('/tasks');
  await expect(page.locator('text=Test task >> text=Failed')).not.toBeVisible();
  
  // Show archived tasks
  await page.click('text=Show archived');
  await expect(page.locator('text=Test task >> text=Failed')).toBeVisible();
});
```

## Future Enhancements

**Not in MVP, but worth considering:**

1. **Batch Retry** - Retry multiple failed tasks at once
2. **Retry with Modifications UI** - Modal to edit config before retry
3. **Auto-retry Policy** - Automatically retry N times on transient failures
4. **Retry Statistics** - Show "Retry count: 3" on task cards
5. **Edge Type Field** - Distinguish "retry" edges from "dependency" edges in schema
6. **Retry Chain Visualization** - Graph view showing original → retry1 → retry2
7. **Smart Retry** - Suggest different environment if original is unhealthy

## Dependencies

**No external dependencies** - uses existing:
- `TaskHarnessService.create_task()`
- `TaskHarnessService.archive_task()`
- `TaskHarnessService.create_task_edge()`
- Task edges table (already exists)

**Schema Changes:** None required

**Migration:** None required

## Rollout Plan

1. **Phase 1: Backend Implementation** (~2-3 hours)
   - Add `retry_task()` method to `TaskHarnessService`
   - Add POST endpoint to `/tasks/{id}/retry`
   - Add API schema types (`TaskRetryRequest`, `TaskRetryResponse`)
   - Write unit tests

2. **Phase 2: Frontend Implementation** (~3-4 hours)
   - Add "Retry" button to task cards
   - Add API client function `retryTask()`
   - Add i18n keys (en + zh)
   - Add retry relationship display in task detail
   - Add toast notifications

3. **Phase 3: Testing** (~2 hours)
   - Integration tests
   - E2E tests
   - Manual QA

4. **Phase 4: Documentation** (~1 hour)
   - Update user guide
   - Add API documentation

**Total effort estimate: ~8-10 hours**

## Security Considerations

- **Permission check**: Only task owner or admin can retry
- **Rate limiting**: Consider adding rate limit to prevent retry spam (future)
- **Audit trail**: Task edges provide full history of retries

## Open Questions

1. **Title prefix?** Should retried tasks have "[Retry]" prefix in title?
   - **Decision:** No, keep original title. Users can see relationship via edges.

2. **Session handling?** Should retry reuse the old session_id?
   - **Decision:** No, create new session. Each retry is independent run.

3. **Auto-start?** Should retried task start immediately or stay QUEUED?
   - **Decision:** Immediately enter queue (current create_task behavior).

4. **Multiple retries?** Can user retry a task that was itself a retry?
   - **Decision:** Yes, no restriction. Edge chain will show full history.

## Summary

This design provides a simple, robust retry mechanism for TaskHarness tasks:

- **User benefit:** One-click retry of failed tasks
- **Implementation:** ~50 lines backend, ~100 lines frontend
- **No schema changes:** Reuses existing tables
- **Audit trail:** Task edges track retry relationships
- **i18n ready:** English and Chinese translations included
- **Extensible:** Easy to add advanced features later

The core principle is **clone and restart** rather than in-place reset, which keeps the implementation simple and provides clear audit history.

> **Implementation update (2026-06-16):** The retry implementation for session-aware
> engines (Agent-SDK, Claude Code) diverged from "clone and restart" — it now reuses
> the **same task** via `send_input()` → resume the session (`--resume` /
> `session_id`) → re-schedule. Only legacy engines create a brand-new task on retry.
> See [2026-06-16 worklog] for details.
