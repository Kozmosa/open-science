# Workspace 目录校验与自动创建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 workspace 时对 `default_workdir` 进行存在性校验，缺失则自动创建；失败则阻止 workspace 创建并返回 400 错误。

**Architecture:** 前端增加 placeholder 展示和 required 校验；后端 Service 层在持久化前调用 `pathlib.Path.mkdir` 自动创建目录；新增 `WorkspaceDirectoryError` 异常，API 层翻译为 400 Bad Request。

**Tech Stack:** Python 3.13, FastAPI, React + TypeScript, Vitest, pytest

---

### Task 1: 后端 Service — 新增异常并在 create_workspace 中校验目录

**Files:**
- Modify: `src/ainrf/workspaces/service.py`

- [ ] **Step 1: 新增 `WorkspaceDirectoryError` 异常类**

在 `WorkspaceDeletionError` 下方添加：

```python
class WorkspaceDirectoryError(ValueError):
    pass
```

- [ ] **Step 2: 在 `create_workspace` 中持久化前校验并创建目录**

在 `create_workspace` 方法中，`self._workspaces[workspace_id] = workspace` 之前插入以下逻辑：

```python
if default_workdir:
    workdir_path = Path(default_workdir)
    if not workdir_path.exists():
        try:
            workdir_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceDirectoryError(
                f"Failed to create workspace directory {default_workdir}: {exc}"
            ) from exc
```

- [ ] **Step 3: 导出新增异常**

检查 `src/ainrf/workspaces/__init__.py` 是否导出了 `WorkspaceDirectoryError`。如果 `__init__.py` 使用 `from .service import *` 或显式导入，确保新增异常被导出。若未导出，添加：

```python
from ainrf.workspaces.service import WorkspaceDirectoryError
```

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/workspaces/service.py
git commit -m "feat: validate and auto-create workspace directory on creation"
```

---

### Task 2: 后端 API 路由 — 处理 `WorkspaceDirectoryError`

**Files:**
- Modify: `src/ainrf/api/routes/workspaces.py`

- [ ] **Step 1: 导入新增异常**

将现有的导入：

```python
from ainrf.workspaces import (
    WorkspaceDeletionError,
    WorkspaceNotFoundError,
    WorkspaceRegistryService,
)
```

修改为：

```python
from ainrf.workspaces import (
    WorkspaceDeletionError,
    WorkspaceDirectoryError,
    WorkspaceNotFoundError,
    WorkspaceRegistryService,
)
```

- [ ] **Step 2: 在 `_translate_workspace_error` 中处理新异常**

在 `_translate_workspace_error` 函数中添加：

```python
if isinstance(exc, WorkspaceDirectoryError):
    return HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 3: Commit**

```bash
git add src/ainrf/api/routes/workspaces.py
git commit -m "feat: translate WorkspaceDirectoryError to 400 Bad Request"
```

---

### Task 3: 后端测试 — 更新现有测试并新增目录创建测试

**Files:**
- Modify: `tests/test_api_v1_routes.py`
- Modify: `tests/test_api_v1_routes.py`

- [ ] **Step 1: 更新 `test_workspace_crud_routes_persist_changes`**

现有测试已包含 `default_workdir`，无需修改其请求体。但需要确认更新后的 create 行为仍然通过。运行现有测试确保未破坏：

```bash
uv run pytest tests/test_api_v1_routes.py::test_workspace_crud_routes_persist_changes -v
```

Expected: PASS

- [ ] **Step 2: 新增测试 — 目录不存在时自动创建成功**

在 `test_workspace_crud_routes_persist_changes` 下方添加：

```python
@pytest.mark.anyio
async def test_create_workspace_auto_creates_missing_directory(tmp_path: Path) -> None:
    target_dir = tmp_path / "auto-created" / "workspace"
    assert not target_dir.exists()

    async with make_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            headers={"X-API-Key": "secret-key"},
            json={
                "label": "Auto Created",
                "description": None,
                "default_workdir": str(target_dir),
                "workspace_prompt": "Auto create test.",
            },
        )

    assert create_response.status_code == 200
    assert target_dir.exists()
    assert target_dir.is_dir()
```

Run:

```bash
uv run pytest tests/test_api_v1_routes.py::test_create_workspace_auto_creates_missing_directory -v
```

Expected: PASS

- [ ] **Step 3: 新增测试 — 目录创建失败时返回 400 且 workspace 不被创建**

在上一测试下方添加：

```python
@pytest.mark.anyio
async def test_create_workspace_rejects_unavailable_directory(tmp_path: Path) -> None:
    # 创建一个文件来阻塞目录创建（同名文件存在时 mkdir 会失败）
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("i am a file", encoding="utf-8")

    async with make_client(tmp_path) as client:
        create_response = await client.post(
            "/v1/workspaces",
            headers={"X-API-Key": "secret-key"},
            json={
                "label": "Blocked",
                "description": None,
                "default_workdir": str(blocked_path),
                "workspace_prompt": "Blocked test.",
            },
        )

    assert create_response.status_code == 400
    detail = create_response.json()["detail"]
    assert "Failed to create workspace directory" in detail

    # 验证 workspace 未被写入 registry
    list_response = await client.get(
        "/v1/workspaces",
        headers={"X-API-Key": "secret-key"},
    )
    assert list_response.status_code == 200
    labels = {item["label"] for item in list_response.json()["items"]}
    assert "Blocked" not in labels
```

Run:

```bash
uv run pytest tests/test_api_v1_routes.py::test_create_workspace_rejects_unavailable_directory -v
```

Expected: PASS

- [ ] **Step 4: 运行所有 workspace 相关测试**

```bash
uv run pytest tests/test_api_v1_routes.py -v -k workspace
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_v1_routes.py
git commit -m "test: workspace directory auto-creation and rejection on failure"
```

---

### Task 4: 前端 — placeholder 与 required 校验

**Files:**
- Modify: `frontend/src/pages/workspaces/WorkspaceManagerCard.tsx`

- [ ] **Step 1: 获取 seed workspace 的 default_workdir 作为 placeholder**

在 `WorkspaceManagerCard` 组件中，在 `workspaces` 定义之后添加：

```typescript
const seedWorkspace = workspaces.find((w) => w.workspace_id === 'workspace-default');
const defaultWorkdirPlaceholder = seedWorkspace?.default_workdir ?? '';
```

- [ ] **Step 2: 为 default_workdir 输入框添加 placeholder 和 required**

找到 `default_workdir` 的 `Input` 组件，修改为：

```tsx
<FormField label={t('pages.workspaces.defaultWorkdirField')}>
  <Input
    aria-label={t('pages.workspaces.defaultWorkdirField')}
    required
    placeholder={defaultWorkdirPlaceholder}
    value={draft.default_workdir}
    onChange={(event) =>
      setDraft((current) => ({ ...current, default_workdir: event.target.value }))
    }
  />
</FormField>
```

- [ ] **Step 3: 前端类型检查**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 无类型错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/workspaces/WorkspaceManagerCard.tsx
git commit -m "feat: add placeholder and required to workspace default_workdir input"
```

---

### Task 5: 前端测试 — 验证 placeholder 和 required

**Files:**
- Modify: `frontend/src/pages/WorkspacesPage.test.tsx`

- [ ] **Step 1: 更新创建测试以验证 placeholder**

在现有 `it('creates a workspace from the manager form', ...)` 测试的 `fireEvent.click(await screen.findByRole('button', { name: 'New workspace' }));` 之后、表单填写之前，添加断言：

```typescript
const workdirInput = screen.getByLabelText('Default workdir') as HTMLInputElement;
expect(workdirInput.placeholder).toBe(defaultWorkspace.default_workdir);
```

- [ ] **Step 2: 新增测试 — required 校验阻止空路径提交**

在创建测试下方添加：

```typescript
it('prevents creating a workspace without default_workdir', async () => {
  mockGetWorkspaces.mockResolvedValueOnce(workspaceList([defaultWorkspace]));

  renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

  fireEvent.click(await screen.findByRole('button', { name: 'New workspace' }));
  fireEvent.change(screen.getByLabelText('Workspace label'), {
    target: { value: 'No Workdir' },
  });
  fireEvent.change(screen.getByLabelText('Workspace prompt'), {
    target: { value: 'Prompt' },
  });

  // default_workdir 留空，尝试提交
  const workdirInput = screen.getByLabelText('Default workdir') as HTMLInputElement;
  expect(workdirInput.required).toBe(true);

  // HTML5 required 校验会阻止表单提交，因此 createWorkspace 不应被调用
  fireEvent.click(screen.getByRole('button', { name: 'Create workspace' }));

  await waitFor(() => {
    expect(mockCreateWorkspace).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: 运行前端测试**

```bash
cd frontend && npm run test:run -- src/pages/WorkspacesPage.test.tsx
```

Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/WorkspacesPage.test.tsx
git commit -m "test: verify workspace default_workdir placeholder and required validation"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 运行后端完整测试**

```bash
uv run pytest tests/test_api_v1_routes.py -v
```

Expected: 全部 PASS

- [ ] **Step 2: 运行前端完整测试**

```bash
cd frontend && npm run test:run
```

Expected: 全部 PASS

- [ ] **Step 3: 运行 lint**

```bash
uv run ruff check . && cd frontend && node_modules/.bin/tsc -b
```

Expected: 无错误

- [ ] **Step 4: 最终 Commit（如有额外修复）**

```bash
git add .
git commit -m "fix: workspace creation validates and auto-creates default_workdir"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] 前端 placeholder → Task 4 Step 2
- [x] 前端 required 校验 → Task 4 Step 2 + Task 5 Step 2
- [x] 后端目录存在性检查 → Task 1 Step 2
- [x] 后端自动创建目录 → Task 1 Step 2
- [x] 后端创建失败阻止 workspace 创建 → Task 1 Step 2 + Task 2 Step 2
- [x] 后端返回 400 错误 → Task 2 Step 2
- [x] 后端测试覆盖 → Task 3
- [x] 前端测试覆盖 → Task 5

**2. Placeholder scan:** 无 TBD、TODO、"implement later" 等占位符。

**3. Type consistency:**
- `WorkspaceDirectoryError` 在 Task 1 中定义，在 Task 2 中导入和处理，名称一致。
- `default_workdir` 在前端后端均保持 `str | None` 类型。
