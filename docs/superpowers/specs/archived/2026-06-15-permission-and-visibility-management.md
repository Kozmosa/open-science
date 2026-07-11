# Project / Workspace / Task 三层权限与可见性管理规范

> [!warning] Historical design
> 本文基于旧 Workspace 单 owner/单 Project 结构和早期 Project collaborator 规则，当前权限能力表、Workspace 暂不共享及 Project–Workspace 关联权限以 [`../2026-07-11-project-task-workspace-domain-design.md`](../2026-07-11-project-task-workspace-domain-design.md) 为准。本文仅保留旧实现审计背景。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 系统化梳理并补齐整个系统中 Project、Workspace、Task 三层抽象的所有权绑定、访问控制和可见性过滤，消除当前实现中的不一致和漏洞。

**Architecture:** 统一采用「认证 → 所有权绑定 → 访问校验」三层防护模型。所有可变资源（Project / Workspace / Task / TaskEdge / EnvironmentRef）在创建时强制绑定 `owner_user_id`，在读/改/删时一律调用 `check_resource_ownership` 或等价过滤逻辑。Project 引入 Collaborator 机制实现多用户共享可见性。

**Tech Stack:** FastAPI + Python 3.13, React 19 + TypeScript + Tailwind CSS v4

---

## 1. 现状审计

### 1.1 基础设施（已就绪，无需新增）

| 组件 | 位置 | 状态 |
|------|------|------|
| `check_resource_ownership(user, owner_id)` | `src/ainrf/auth/permissions.py:27-42` | ✅ 已实现：admin 绕行，NULL owner → 403，owner 不匹配 → 403 |
| `get_current_user(request)` | `src/ainrf/auth/permissions.py:8-13` | ✅ 已实现：从 `request.state.current_user` 读取，未认证 → 401 |
| `is_admin(user)` / `require_admin(user)` | `src/ainrf/auth/permissions.py:45-53` | ✅ 已实现 |
| JWT 认证中间件 | `src/ainrf/api/middleware/__init__.py:148-205` | ✅ 已实现：Bearer / Cookie / API Key 三种方式 |
| `ProjectRecord.owner_user_id` | `src/ainrf/projects/models.py:16` | ✅ 字段存在，默认为 `None` |
| `WorkspaceRecord.owner_user_id` | `src/ainrf/workspaces/models.py:17` | ✅ 字段存在，默认为 `None` |
| `Task.owner_user_id` | AgenticResearcher 模型 | ✅ 字段存在 |
| `ProjectRegistryService.list_projects(owner_user_id=, collaborator_project_ids=)` | `src/ainrf/projects/service.py:82-97` | ✅ 已支持过滤参数，但路由层未使用 |
| `WorkspaceRegistryService.list_workspaces(owner_user_id=)` | `src/ainrf/workspaces/service.py:74-85` | ✅ 已支持过滤参数 |
| `project_collaborators` 表 | `src/ainrf/db/migrations/auth.py:40-49` | ✅ SQLite 表已创建 |
| `AuthService.add_collaborator / remove_collaborator / list_collaborators / get_user_project_ids` | `src/ainrf/auth/service.py:322-370` | ✅ CRUD 方法完整 |

### 1.2 各层端点权限现状矩阵

#### Project 路由 (`src/ainrf/api/routes/projects.py`)

| 端点 | 行号 | 认证 | 所有权检查 | 问题 |
|------|------|------|-----------|------|
| `GET /projects` | 147 | ✅ `get_current_user` | **❌ 返回全部** | 任何登录用户可见所有 project |
| `POST /projects` | 158 | ✅ `get_current_user` | **❌ 未绑定 owner** | `create_project()` 未传 `owner_user_id`，默认为 `None` |
| `GET /projects/{id}` | 172 | ✅ `get_current_user` | **❌** | 任何登录用户可读取任意 project |
| `PATCH /projects/{id}` | 183 | ✅ `get_current_user` | **❌** | 任何登录用户可修改任意 project |
| `DELETE /projects/{id}` | 205 | ✅ `get_current_user` | **❌** | 任何登录用户可删除任意 project |
| `GET /projects/{id}/environment-refs` | 219 | **❌ 无认证** | **❌** | **未登录即可访问** |
| `POST /projects/{id}/environment-refs` | 235 | **❌ 无认证** | **❌** | **未登录即可访问** |
| `PATCH /projects/{id}/environment-refs/{env_id}` | 260 | **❌ 无认证** | **❌** | **未登录即可访问** |
| `DELETE /projects/{id}/environment-refs/{env_id}` | 291 | **❌ 无认证** | **❌** | **未登录即可访问** |
| `GET /projects/{id}/cost-summary` | 305 | ✅ `get_current_user` | **❌** | 任何登录用户可查看成本 |
| `GET /projects/{id}/task-edges` | 354 | ✅ `get_current_user` | **❌** | 任何登录用户可读取任意 project 的 edges |
| `POST /projects/{id}/task-edges` | 372 | ✅ `get_current_user` | **❌** | 任何登录用户可创建 edge |
| `DELETE /task-edges/{edge_id}` | 391 | ✅ `get_current_user` | **❌** | 任何登录用户可删除任意 edge |
| `GET /projects/{id}/tasks` | 401 | ✅ + owner filter | **部分** | admin 看全部，非 admin 只看自己的 task |
| `PUT /projects/{id}/collaborators` | 446 | ✅ `get_current_user` + `check_resource_ownership` | **✅（唯一正确的）** | 仅 owner/admin 可添加 |
| `DELETE /projects/{id}/collaborators/{user_id}` | 461 | ✅ `get_current_user` + `check_resource_ownership` | **✅（唯一正确的）** | 仅 owner/admin 可移除 |
| `GET /projects/{id}/collaborators` | 433 | ✅ `get_current_user` | **❌** | 任何登录用户可查看 collaborator 列表 |

#### Workspace 路由 (`src/ainrf/api/routes/workspaces.py`)

| 端点 | 行号 | 认证 | 所有权检查 | 问题 |
|------|------|------|-----------|------|
| `GET /workspaces` | 65 | ✅ | **✅** `is_admin` 分支 + `owner_user_id` 过滤 | 无 |
| `POST /workspaces` | 83 | ✅ | **✅** 创建时绑定 `owner_user_id=user["id"]` | 无 |
| `GET /workspaces/{id}` | 104 | ✅ | **✅** `check_resource_ownership` | 无 |
| `PATCH /workspaces/{id}` | 116 | ✅ | **✅** `check_resource_ownership` | 无 |
| `DELETE /workspaces/{id}` | 140 | ✅ | **✅** `check_resource_ownership` | 无 |

#### Task 路由 (`src/ainrf/api/routes/tasks.py`)

| 端点 | 行号 | 认证 | 所有权检查 | 问题 |
|------|------|------|-----------|------|
| `POST /tasks` | 242 | ✅ | **✅** 创建时绑定 `owner_user_id=user["id"]` | 无 |
| `GET /tasks` | 295 | ✅ | **✅** `_task_list_owner_filter` | admin 看全部，非 admin 看自己的 |
| `GET /tasks/{id}` | 333 | ✅ | **✅** `_assert_task_owner` → `check_resource_ownership` | 无 |
| `POST /tasks/{id}/cancel` | 339 | ✅ | **✅** `_assert_task_owner` | 无 |
| `POST /tasks/{id}/pause` | 349 | ✅ | **✅** `_assert_task_owner` | 无 |
| `POST /tasks/{id}/resume` | 359 | ✅ | **✅** `_assert_task_owner` | 无 |
| `POST /tasks/{id}/prompt` | 369 | ✅ | **✅** `_assert_task_owner` | 无 |
| `DELETE /tasks/{id}` (archive) | 383 | ✅ | **✅** `_assert_task_owner` | 无 |
| `DELETE /tasks/{id}/permanent` | 400 | ✅ | **✅** `_assert_task_owner` | 无 |
| `PATCH /tasks/{id}/project` | 407 | ✅ | **✅** `_assert_task_owner` | 无 |
| `PATCH /tasks/{id}` | 427 | ✅ | **✅** `_assert_task_owner` | 无 |
| `POST /tasks/{id}/retry` | 439 | ✅ | **✅** `check_resource_ownership` | 无 |
| `GET /tasks/{id}/output` | 474 | ✅ | **✅** `check_resource_ownership` | 无 |
| `GET /tasks/{id}/messages` | 515 | ✅ | **✅** `_assert_task_owner` | 无 |
| `GET /tasks/{id}/stream` | 533 | ✅ | **✅** `_assert_task_stream_access` | 无 |
| `GET /tasks/token-usage` | 319 | ✅ | **✅** `_task_list_owner_filter` | 无 |

### 1.3 前端类型现状

| 类型 | 文件位置 | `owner_user_id` 字段 | 问题 |
|------|---------|---------------------|------|
| `ProjectRecord` | `frontend/src/shared/types/index.ts:90-98` | **❌ 缺失** | 前端完全不知道 project 有 owner |
| `WorkspaceRecord` | 同上:118-127 | **❌ 缺失** | 前端完全不知道 workspace 有 owner |
| `TaskSummary` | 同上:163-189 | ✅ `owner_user_id?: string` (line 179) | 可选，但至少存在 |

---

## 2. 问题分类与严重程度

### 🔴 Critical（安全漏洞，立即修复）

| # | 问题 | 影响 |
|---|------|------|
| C1 | **6 个 environment-refs 端点无认证**（projects.py:219-301） | 未登录用户可读写 project 的环境引用 |
| C2 | **Project CRUD 无所有权检查**（读/改/删全部 project） | 任何登录用户可读写删除任意用户的 project |
| C3 | **POST /projects 不绑定 owner**（projects.py:162-165） | 创建的 project 成为「无主」资源，无法通过 `check_resource_ownership` 保护；collaborator 端点对非 admin 全部 403 |

### 🟡 High（功能缺陷，尽快修复）

| # | 问题 | 影响 |
|---|------|------|
| H1 | `GET /projects` 返回全部 project | 用户 list 中看到其他用户的 project |
| H2 | TaskEdge CRUD 无所有权检查 | 用户可操作其他 project 的 task edges |
| H3 | Cost summary 无所有权检查 | 用户可查看其他 project 的成本数据 |
| H4 | Collaborator list 无所有权检查 | 用户可查看其他 project 的协作者列表 |
| H5 | `GET /projects/{id}/tasks` 仅按 task owner 过滤，不验证 project 可见性 | 如果一个 project 对用户不可见，用户仍可通过 project_id 参数列出该 project 下的 task（只要那些 task 是该用户自己的） |

### 🟢 Medium（前端缺失，影响 UX）

| # | 问题 | 影响 |
|---|------|------|
| M1 | 前端 `ProjectRecord` 缺少 `owner_user_id` | UI 无法展示 project 所有者信息 |
| M2 | 前端 `WorkspaceRecord` 缺少 `owner_user_id` | UI 无法展示 workspace 所有者信息 |
| M3 | 前端无法区分「我的项目」和「共享给我的项目」 | 所有 project 平铺展示 |
| M4 | 前端无法在 UI 中管理 collaborator | collaborator 只有 API，无前端入口 |

---

## 3. 统一权限模型设计

### 3.1 三层防护模型

```
请求到达
    │
    ▼
┌──────────────────────┐
│ Layer 1: 认证         │  ← JWT middleware (已验证)
│ get_current_user()    │     └─ 未认证 → 401
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Layer 2: 资源定位     │  ← service.get_*(id)
│ 获取目标资源          │     └─ 不存在 → 404
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ Layer 3: 所有权校验   │  ← check_resource_ownership(user, resource.owner_user_id)
│                      │     ├─ admin → 放行
│                      │     ├─ owner 匹配 → 放行
│                      │     ├─ collaborator (仅 Project) → 放行
│                      │     └─ 否则 → 403
└──────────────────────┘
```

### 3.2 Project 可见性模型（最复杂的一层）

Project 的可见性由 **两层权限** 共同决定：

```
用户对 Project 可见 ⇔
    user.role == "admin"
    OR project.owner_user_id == user.id
    OR user.id ∈ project_collaborators(project.id)
```

| 操作 | 权限要求 |
|------|---------|
| **LIST** | 返回满足可见性条件的 projects（owner + collaborator） |
| **READ** | owner OR collaborator OR admin |
| **CREATE** | 任何已认证用户均可创建；自动绑定为 owner |
| **UPDATE** | owner OR admin（collaborator 不可修改 project 本身） |
| **DELETE** | owner OR admin（collaborator 不可删除 project） |
| **管理 Collaborator** | owner OR admin |
| **管理 Environment Refs** | owner OR admin |
| **管理 Task Edges** | owner OR collaborator OR admin（只要是 project 可见用户即可操作） |
| **查看 Tasks** | owner OR collaborator OR admin（返回 project 下所有 task，不只自己的） |
| **查看 Cost Summary** | owner OR collaborator OR admin |

### 3.3 Workspace 可见性模型

保持现有实现（已正确），无需变更：

| 操作 | 权限要求 |
|------|---------|
| **LIST** | admin 看全部；非 admin 只看 `owner_user_id == user.id` |
| **READ / UPDATE / DELETE** | owner OR admin（通过 `check_resource_ownership`） |
| **CREATE** | 任何已认证用户均可；自动绑定为 owner |

### 3.4 Task 可见性模型

保持现有实现（已正确），无需变更：

| 操作 | 权限要求 |
|------|---------|
| **LIST** | admin 看全部；非 admin 只看 `owner_user_id == user.id` |
| **READ / 所有操作** | owner OR admin（通过 `_assert_task_owner`） |
| **CREATE** | 任何已认证用户均可；自动绑定为 owner |

**注意**：`GET /projects/{id}/tasks` 的语义需要修正——当前按 task owner 过滤，修正后应当检查 project 可见性：如果用户对 project 可见（owner/collaborator/admin），则返回 project 下所有 task（不限于自己的 task）。这符合「project 是协作单元」的设计意图。

---

## 4. 后端实现方案

### 4.1 Project 路由变更清单 (`src/ainrf/api/routes/projects.py`)

#### 4.1.1 新增辅助函数

```python
def _check_project_visible(
    user: dict,
    project: ProjectRecord,
    auth_svc,
    *,
    require_owner: bool = False,
) -> None:
    """验证用户对 project 的可见性。
    
    Args:
        require_owner: 如果为 True，collaborator 不被视为有权限（用于 update/delete 等写操作）。
    """
    # admin 全权限
    if user.get("role") == "admin":
        return
    
    # owner 全权限
    if project.owner_user_id == user["id"]:
        return
    
    # collaborator 有读权限（除非 require_owner）
    if not require_owner and auth_svc is not None:
        collab_ids = auth_svc.get_user_project_ids(user["id"])
        if project.project_id in collab_ids:
            return
    
    raise HTTPException(status_code=403, detail="无权访问此项目")


def _get_visible_project_ids(user: dict, project_service, auth_svc) -> set[str]:
    """返回用户可见的全部 project_id 集合。"""
    if user.get("role") == "admin":
        return {p.project_id for p in project_service.list_projects()}
    
    owned = {p.project_id for p in project_service.list_projects(owner_user_id=user["id"])}
    collab = set(auth_svc.get_user_project_ids(user["id"])) if auth_svc else set()
    return owned | collab
```

#### 4.1.2 端点变更表

| 端点 | 变更内容 |
|------|---------|
| `GET /projects` | 调用 `_get_visible_project_ids` 过滤列表，返回用户可见的 projects |
| `POST /projects` | 在 `create_project()` 调用中增加 `owner_user_id=user["id"]` |
| `GET /projects/{id}` | 增加 `_check_project_visible(user, project, auth_svc)` 调用 |
| `PATCH /projects/{id}` | 增加 `_check_project_visible(user, project, auth_svc, require_owner=True)` |
| `DELETE /projects/{id}` | 增加 `_check_project_visible(user, project, auth_svc, require_owner=True)` |
| `GET /projects/{id}/environment-refs` | 增加 `get_current_user` + `_check_project_visible` |
| `POST /projects/{id}/environment-refs` | 增加 `get_current_user` + `_check_project_visible(require_owner=True)` |
| `PATCH /projects/{id}/environment-refs/{env_id}` | 增加 `get_current_user` + `_check_project_visible(require_owner=True)` |
| `DELETE /projects/{id}/environment-refs/{env_id}` | 增加 `get_current_user` + `_check_project_visible(require_owner=True)` |
| `GET /projects/{id}/cost-summary` | 增加 `_check_project_visible` |
| `GET /projects/{id}/task-edges` | 增加 `_check_project_visible` |
| `POST /projects/{id}/task-edges` | 增加 `_check_project_visible` |
| `DELETE /task-edges/{edge_id}` | 先查出 edge 所属 project，再 `_check_project_visible` |
| `GET /projects/{id}/tasks` | **语义变更**：检查 project 可见性后，返回 project 下 **所有** task（不再按 task owner 过滤）；但前端列表 UI 可在展示层做视觉区分 |
| `GET /projects/{id}/collaborators` | 增加 `_check_project_visible` |

#### 4.1.3 `DELETE /task-edges/{edge_id}` 跨 project 校验

```python
@task_edges_router.delete("/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_edge(edge_id: str, request: Request) -> None:
    user = get_current_user(request)
    service = _get_project_service(request)
    auth_svc = _get_auth_service(request)
    try:
        edge = service.get_task_edge(edge_id)  # 需要新增 get_task_edge 方法
        project = service.get_project(edge.project_id)
        _check_project_visible(user, project, auth_svc)
        service.delete_task_edge(edge_id)
    except Exception as exc:
        raise _translate_task_edge_error(exc) from exc
```

### 4.2 ProjectRegistryService 变更 (`src/ainrf/projects/service.py`)

需要新增一个方法：

```python
def get_task_edge(self, edge_id: str) -> TaskEdgeRecord:
    """获取单个 task edge。"""
    self.initialize()
    try:
        return self._task_edges[edge_id]
    except KeyError as exc:
        raise TaskEdgeNotFoundError(edge_id) from exc
```

其他方法无需变更——`list_projects()` 已经支持 `owner_user_id` 和 `collaborator_project_ids` 过滤参数。

### 4.3 Workspace 路由

**无需变更**——当前实现已完全正确。

### 4.4 Task 路由

**核心 CRUD 无需变更**——当前实现已完全正确。

唯一的语义调整在 `GET /projects/{id}/tasks`（见 4.1.2 最后一行），但这个端点属于 Project 路由，已在 4.1 中覆盖。

### 4.5 API Schemas 变更 (`src/ainrf/api/schemas.py`)

无需新增字段——`ProjectResponse`（line 68）和 `WorkspaceResponse`（line 446）已经包含 `owner_user_id`。

---

## 5. 前端实现方案

### 5.1 TypeScript 类型补全 (`frontend/src/shared/types/index.ts`)

```typescript
export interface ProjectRecord {
  project_id: string;
  name: string;
  description: string | null;
  default_workspace_id: string | null;
  default_environment_id: string | null;
  created_at: string;
  updated_at: string;
  owner_user_id: string | null;  // ← 新增
}

export interface WorkspaceRecord {
  workspace_id: string;
  project_id: string;
  label: string;
  description: string | null;
  default_workdir: string | null;
  workspace_prompt: string;
  created_at: string;
  updated_at: string;
  owner_user_id: string | null;  // ← 新增
}
```

### 5.2 UI 展示建议（后续 PR）

以下变更属于 UX 增强，可在本 PR 中仅完成类型补全，UI 部分另开 PR：

| 页面 | 建议变更 |
|------|---------|
| `ProjectsPage` | 增加「我的项目」/「共享给我的」分段或 filter tabs；列表项显示 owner 标识 |
| `Workspace` 列表 | 显示 owner 信息 |
| Project 详情页 | 增加 Collaborator 管理面板（调用已有 API） |
| Task 列表 | 在 project 协作场景下展示 task owner avatar/name |

---

## 6. 数据迁移

### 6.1 已有数据的 `owner_user_id` 回填

对于已存在的 `owner_user_id = None` 的 project：

**策略**：在服务启动时（`initialize()` 之后）执行一次回填扫描：
- 如果存在 `owner_user_id` 为 `None` 的 project，将其 `owner_user_id` 设置为 `"admin"`（第一个 admin 用户的 ID）
- 记录 WARNING 日志，提醒管理员手动审核

```python
# 在 ProjectRegistryService.initialize() 末尾新增
def _backfill_null_owners(self) -> None:
    """将 owner_user_id 为 None 的 project 回填为第一个 admin 用户。"""
    null_owner_projects = [
        p for p in self._projects.values() if p.owner_user_id is None
    ]
    if null_owner_projects:
        logger.warning(
            "backfill_null_project_owners count=%d projects=%s",
            len(null_owner_projects),
            [p.project_id for p in null_owner_projects],
        )
        # 尝试从 auth service 获取 admin 用户 ID
        # 如果不可用，使用 "admin" 字符串作为 fallback
        for p in null_owner_projects:
            p.owner_user_id = "admin"
        self._persist()
```

**Workspace 不需要回填**——workspace 的创建 API 从实现之初就正确绑定了 owner。

**Task 不需要回填**——task 创建时正确绑定了 owner。

### 6.2 Collaborator 数据

`project_collaborators` 表为空是正常的——这是一个可选功能，没有历史数据需要迁移。

---

## 7. 测试策略

### 7.1 后端单元测试（新增）

| 测试文件 | 测试内容 |
|---------|---------|
| `tests/test_project_permissions.py` | Project CRUD 的所有权校验：owner 可操作，非 owner 被 403，admin 全权限 |
| `tests/test_project_collaborator_visibility.py` | Collaborator 可见性：collaborator 可在 list 中看到 project，可读但不可写 |
| `tests/test_environment_refs_permissions.py` | Environment refs 端点：未认证 → 401，非 member → 403 |
| `tests/test_task_edges_permissions.py` | Task edge 操作：跨 project 删除 edge 被拒绝 |

### 7.2 现有测试兼容性

- `check_resource_ownership` 的行为未变，Workspace 和 Task 的现有测试不受影响
- Project 测试需要更新：原来不检查所有权的测试用例需要在请求中携带正确的用户上下文

---

## 8. 实施任务分解

### Phase 1: 后端安全修复（Critical + High）

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 1.1 | 新增 `_check_project_visible` 辅助函数 | `projects.py` | 🔴 |
| 1.2 | `POST /projects` 绑定 `owner_user_id` | `projects.py:162-165` | 🔴 |
| 1.3 | 为 6 个 environment-refs 端点添加认证和所有权检查 | `projects.py:219-301` | 🔴 |
| 1.4 | `GET /projects` 按可见性过滤 | `projects.py:147-154` | 🟡 |
| 1.5 | `GET/PATCH/DELETE /projects/{id}` 增加所有权检查 | `projects.py:172-211` | 🟡 |
| 1.6 | Task edge 端点增加 project 可见性检查 | `projects.py:354-397` | 🟡 |
| 1.7 | Cost summary 增加 project 可见性检查 | `projects.py:305` | 🟡 |
| 1.8 | Collaborator list 增加 project 可见性检查 | `projects.py:433` | 🟡 |
| 1.9 | `GET /projects/{id}/tasks` 语义修正 | `projects.py:401-429` | 🟡 |
| 1.10 | `ProjectRegistryService.get_task_edge()` 新增方法 | `service.py` | 🟡 |
| 1.11 | `_backfill_null_owners()` 数据回填 | `service.py` | 🟡 |

### Phase 2: 前端类型补全

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 2.1 | `ProjectRecord` 增加 `owner_user_id` | `frontend/src/shared/types/index.ts` | 🟢 |
| 2.2 | `WorkspaceRecord` 增加 `owner_user_id` | 同上 | 🟢 |

### Phase 3: 前端 UI 增强（后续 PR）

| # | 任务 | 描述 |
|---|------|------|
| 3.1 | Project 列表分段 | 「我的项目」/「共享给我的」tab 切换 |
| 3.2 | Collaborator 管理面板 | Project 详情页增加成员管理 UI |
| 3.3 | Owner 信息展示 | Project/Workspace 列表项展示 owner display name |

---

## 9. 风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 已有 `owner_user_id=None` 的 project 在回填后访问权限变化 | 高 | 中 | 回填时记录 WARNING 日志；优先回填为 admin 用户 |
| 前端未适配新 403 响应导致用户体验断裂 | 中 | 低 | 后端变更不影响响应格式；前端只需处理已有 403 状态码 |
| Collaborator 功能实际使用率低 | 高 | 低 | 本 PR 仅补齐安全基础，不强制推广使用 |
| `GET /projects/{id}/tasks` 语义变更影响前端 | 中 | 中 | 与前端协调：前端 Task 列表页面已按 project 过滤，变更后只是返回更多 task，不会导致功能异常 |
