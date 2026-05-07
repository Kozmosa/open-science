# Workspace 创建时目录校验与自动创建

## 背景

当前创建 workspace 时，`default_workdir` 仅作为字符串写入 registry，系统不校验目录是否存在，也不会自动创建。这导致用户在创建 workspace 后若未手动创建对应目录，直接新建 task 时会因目录不存在而报错。

## 目标

创建 workspace 时，对 `default_workdir` 进行存在性校验：若目录不存在则自动创建；创建失败则阻止 workspace 创建并返回明确的错误信息。

## 设计

### 前端行为

1. **Placeholder**: `default_workdir` 输入框展示 seed workspace（`workspace-default`）的 `default_workdir` 作为 placeholder，提示用户默认路径。
2. **必填校验**: `default_workdir` 设为 required 字段。用户留空时，HTML5 表单验证阻止提交。

### 后端行为

在 `WorkspaceRegistryService.create_workspace()` 中，写入 registry **之前**执行以下步骤：

1. 确认 `default_workdir` 非空（防御性校验）。
2. 将路径转为 `pathlib.Path`。
3. 检查目录是否存在：
   - 若存在，跳过。
   - 若不存在，调用 `path.mkdir(parents=True, exist_ok=True)` 自动创建。
4. 若创建失败（如权限不足、路径无效），抛出 `WorkspaceDirectoryError`，**不写入 registry**。

在 API 层，`WorkspaceDirectoryError` 被翻译为 `400 Bad Request`，返回明确的错误详情。

### 异常定义

新增异常类：

```python
class WorkspaceDirectoryError(ValueError):
    pass
```

在 `_translate_workspace_error` 中映射：

```python
if isinstance(exc, WorkspaceDirectoryError):
    return HTTPException(status_code=400, detail=str(exc))
```

### 数据流

```
用户填写表单 → 前端 required 校验 → 提交到 POST /v1/workspaces
    → 后端 create_workspace
        → 校验 default_workdir 非空
        → 检查目录存在性
        → 不存在则 mkdir(parents=True, exist_ok=True)
        → 失败则抛 WorkspaceDirectoryError → API 返回 400
        → 成功则写入 registry → API 返回 200 + workspace 数据
```

### 错误处理

| 场景 | 前端行为 | 后端行为 | HTTP 状态 |
|------|----------|----------|-----------|
| default_workdir 留空 | HTML5 阻止提交，显示 required 提示 | 不接收请求 | — |
| 目录已存在 | 正常提交 | 跳过创建，继续写入 registry | 200 |
| 目录不存在，创建成功 | 正常提交 | 自动创建，写入 registry | 200 |
| 目录不存在，创建失败（权限不足等） | 显示 API 返回的错误信息 | 抛 WorkspaceDirectoryError，不写入 registry | 400 |

### 测试覆盖

- **API 测试**:
  - 更新现有测试：`default_workdir` 必填。
  - 新增测试：目录不存在时自动创建成功，workspace 正常写入 registry。
  - 新增测试：目录创建失败时返回 400，且 workspace 未被写入 registry。
- **前端测试**:
  - 更新 `WorkspacesPage.test.tsx`：验证 placeholder 显示和 required 校验行为。

## 涉及文件

- `frontend/src/pages/workspaces/WorkspaceManagerCard.tsx`
- `src/ainrf/workspaces/service.py`
- `src/ainrf/api/routes/workspaces.py`
- `tests/test_api_v1_routes.py`
- `frontend/src/pages/WorkspacesPage.test.tsx`

## 兼容性

- 现有已创建的 workspace 不受影响（只修改创建流程）。
- 更新 workspace 的 `default_workdir` 时**不**触发目录创建（保持现有行为，避免意外副作用）。
