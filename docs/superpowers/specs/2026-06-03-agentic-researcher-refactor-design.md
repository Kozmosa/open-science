# AgenticResearcher 架构重构设计

## 一、背景与问题

### 1.1 当前系统的混乱点

当前 scholar-agent 系统存在以下架构问题：

1. **任务系统双轨制**
   - `src/ainrf/tasks/` - 旧的 ManagedTask 系统（基于 tmux window 的任务管理）
   - `src/ainrf/task_harness/` - 新的 TaskHarness 系统（支持多执行引擎）
   - 用户不清楚该用哪个系统，API 也分散在不同路由

2. **鉴权系统多层混杂**
   - JWT + 用户角色管理
   - Bearer token + API key 双通道
   - 项目协作者权限（project_collaborators）
   - 环境访问控制（environment_access）
   - 权限检查逻辑散落在各个模块

3. **Agent 概念模糊**
   - `task_harness` 中的 research agent profile（研究员 agent）
   - execution engines 中隐含的 agent 执行逻辑
   - terminal sessions 中的 agent_session_name
   - 没有统一的 agent 抽象层，概念重叠且难以理解

4. **用户心智负担重**
   - 创建任务需要理解 workspace、environment、binding、profile、engine 等多个概念
   - 前端表单复杂，有大量可选配置项
   - 难以快速上手

### 1.2 重构目标

1. **简化用户心智模型** - 用户只需理解"项目 → 任务 → 执行"这样的线性流程
2. **清晰的模块边界** - 任务调度、执行引擎、鉴权、Agent 各司其职，通过明确的接口通信
3. **统一的抽象层** - 废弃双轨任务系统，全部迁移到统一的 AgenticResearcher 架构

## 二、核心设计

### 2.1 两层架构

我们将系统重构为清晰的两层架构：

```
AgenticResearcher = HarnessEngine + Skills + Prompt
```

**第一层：HarnessEngine（执行引擎层）**
- 对应底层执行能力：`claude-code`、`agent-sdk`、`codex-app-server`
- 职责：启动执行、IO 流管理、进程生命周期控制
- 提供统一的 `HarnessEngine` 协议

**第二层：AgenticResearcher（研究员层）**
- 组合 HarnessEngine + Skills + Prompt，形成完整的工作单元
- 预设两种研究员类型：
  - **vanilla** - 无预置 skill/mcp，允许用户外挂
  - **aris-researcher** - 默认挂载 ARIS skills（research-pipeline、research-lit、research-refine-pipeline）

### 2.2 核心抽象定义

#### AgenticResearcher 模型

```python
# src/ainrf/agentic_researcher/models.py

class AgenticResearcherType(StrEnum):
    VANILLA = "vanilla"
    ARIS = "aris-researcher"

@dataclass
class AgenticResearcher:
    """统一的 Agentic Researcher 抽象"""
    type: AgenticResearcherType
    harness_engine: HarnessEngineType
    skills: list[str]
    mcp_servers: list[str]
    system_prompt: str | None
    
    @classmethod
    def vanilla(cls, engine: HarnessEngineType, user_skills: list[str] = None) -> AgenticResearcher:
        """无预置，允许用户外挂 skill/mcp"""
        return cls(
            type=AgenticResearcherType.VANILLA,
            harness_engine=engine,
            skills=user_skills or [],
            mcp_servers=[],
            system_prompt=None
        )
    
    @classmethod
    def aris(cls, engine: HarnessEngineType) -> AgenticResearcher:
        """默认挂载 ARIS skills"""
        return cls(
            type=AgenticResearcherType.ARIS,
            harness_engine=engine,
            skills=["research-pipeline", "research-lit", "research-refine-pipeline"],
            mcp_servers=[],
            system_prompt=ARIS_SYSTEM_PROMPT
        )
```

#### HarnessEngine 协议

```python
# src/ainrf/harness_engine/base.py

class HarnessEngineType(StrEnum):
    CLAUDE_CODE = "claude-code"
    AGENT_SDK = "agent-sdk"
    CODEX_APP_SERVER = "codex-app-server"

class HarnessEngine(Protocol):
    """执行引擎协议"""
    
    async def launch(self, context: ExecutionContext) -> ExecutionHandle:
        """启动执行"""
        ...
    
    async def send_input(self, handle: ExecutionHandle, text: str) -> None:
        """发送输入"""
        ...
    
    async def stream_output(self, handle: ExecutionHandle) -> AsyncIterator[OutputEvent]:
        """流式输出"""
        ...
    
    async def cancel(self, handle: ExecutionHandle) -> None:
        """取消执行"""
        ...
```

#### 统一的任务模型

```python
# src/ainrf/agentic_researcher/models.py

class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    """统一的任务模型，替代 ManagedTask 和 TaskHarness 的双轨"""
    task_id: str
    project_id: str
    workspace_id: str
    environment_id: str
    
    # Researcher 配置
    researcher_type: AgenticResearcherType
    harness_engine: HarnessEngineType
    
    # 执行状态
    status: TaskStatus
    title: str
    prompt: str
    
    # 可选的用户外挂
    user_skills: list[str]
    user_mcp_servers: list[str]
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # 所有权
    owner_user_id: str
    
    # 执行结果
    exit_code: int | None = None
    error_summary: str | None = None
```

### 2.3 模块结构重组

#### 新的目录结构

```
src/ainrf/
├── agentic_researcher/          # 新增：AgenticResearcher 层
│   ├── __init__.py
│   ├── models.py                # AgenticResearcher, Task, TaskStatus
│   ├── service.py               # AgenticResearcherService (任务 CRUD)
│   ├── presets.py               # vanilla, aris 预设工厂
│   └── registry.py              # researcher 配置注册表
│
├── harness_engine/              # 重构自 task_harness/
│   ├── __init__.py
│   ├── base.py                  # HarnessEngine 协议定义
│   ├── context.py               # ExecutionContext, ExecutionHandle
│   ├── events.py                # OutputEvent, EngineEvent
│   ├── engines/
│   │   ├── claude_code.py       # 原 engines/claude_code.py
│   │   ├── agent_sdk.py         # 原 engines/agent_sdk.py
│   │   └── codex_app_server.py  # 原 engines/codex.py
│   └── launcher.py              # 启动器逻辑
│
├── auth/                        # 保持不变，但清理权限逻辑
│   ├── service.py               # 用户认证
│   ├── permissions.py           # 分层权限检查
│   └── models.py
│
├── tasks/                       # 删除整个目录
│
├── environments/                # 保留
├── terminal/                    # 保留
├── workspaces/                  # 保留
└── api/
    └── routes/
        └── tasks.py             # 简化为直接调用 AgenticResearcherService
```

#### 删除的模块

- `src/ainrf/tasks/` - 整个目录删除（ManagedTask 系统）
- `src/ainrf/task_harness/models.py` - 删除复杂的 TaskDetail, TaskListItem
- `src/ainrf/task_harness/service.py` - 重构为 AgenticResearcherService
- `src/ainrf/task_harness/prompting.py` - 简化，合并到 presets.py
- 部分 `src/ainrf/task_harness/artifacts.py` - 简化快照逻辑

### 2.4 权限系统分层

将复杂的权限逻辑重构为清晰的三层：

```python
# src/ainrf/auth/permissions.py

class PermissionLayer(StrEnum):
    USER = "user"          # 用户级：登录认证
    PROJECT = "project"    # 项目级：协作者检查
    RESOURCE = "resource"  # 资源级：任务、环境所有权

def check_user_authenticated(request: Request) -> User:
    """第一层：用户认证"""
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未认证")
    return user

def check_project_access(user: User, project_id: str, required_role: str = "member") -> None:
    """第二层：项目协作权限"""
    # 简化实现：所有认证用户都能访问所有项目
    # 如果未来需要项目隔离，在这里加逻辑
    pass

def check_resource_ownership(user: User, resource_owner_id: str, allow_admin: bool = True) -> None:
    """第三层：资源所有权"""
    if allow_admin and user.role == "admin":
        return
    if user.id != resource_owner_id:
        raise HTTPException(status_code=403, detail="无权访问此资源")
```

**简化点**：
- 删除复杂的 `project_collaborators` 表逻辑
- 删除复杂的 `environment_access` 表逻辑
- 统一为三层检查，逻辑清晰

## 三、API 设计

### 3.1 简化后的任务 API

```python
# src/ainrf/api/routes/tasks.py (重写后)

@router.post("/tasks")
async def create_task(request: Request, payload: TaskCreateRequest) -> TaskResponse:
    """创建任务 - 唯一入口"""
    user = check_user_authenticated(request)
    check_project_access(user, payload.project_id)
    
    service = _get_researcher_service(request)
    
    # 根据 researcher_type 自动选择预设
    if payload.researcher_type == "vanilla":
        researcher = AgenticResearcher.vanilla(
            engine=payload.harness_engine,
            user_skills=payload.skills  # 用户外挂
        )
    elif payload.researcher_type == "aris-researcher":
        researcher = AgenticResearcher.aris(
            engine=payload.harness_engine
        )
    
    task = await service.create_task(
        project_id=payload.project_id,
        workspace_id=payload.workspace_id,
        environment_id=payload.environment_id,
        researcher=researcher,
        prompt=payload.prompt,
        owner_user_id=user.id
    )
    return task


@router.get("/tasks")
async def list_tasks(request: Request, project_id: str) -> TaskListResponse:
    """列出任务 - 自动过滤权限"""
    user = check_user_authenticated(request)
    check_project_access(user, project_id)
    
    service = _get_researcher_service(request)
    tasks = await service.list_tasks(project_id=project_id, user_id=user.id)
    return {"items": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> TaskResponse:
    """获取任务详情"""
    user = check_user_authenticated(request)
    service = _get_researcher_service(request)
    
    task = await service.get_task(task_id)
    check_resource_ownership(user, task.owner_user_id)
    
    return task


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> None:
    """取消任务 - 统一接口"""
    user = check_user_authenticated(request)
    service = _get_researcher_service(request)
    
    task = await service.get_task(task_id)
    check_resource_ownership(user, task.owner_user_id)
    
    await service.cancel_task(task_id)


@router.post("/tasks/{task_id}/retry")
async def retry_task(request: Request, task_id: str) -> TaskResponse:
    """重试任务"""
    user = check_user_authenticated(request)
    service = _get_researcher_service(request)
    
    task = await service.get_task(task_id)
    check_resource_ownership(user, task.owner_user_id)
    
    new_task = await service.retry_task(task_id)
    return new_task


@router.get("/tasks/{task_id}/output")
async def get_task_output(request: Request, task_id: str, after_seq: int = 0) -> TaskOutputResponse:
    """获取任务输出"""
    user = check_user_authenticated(request)
    service = _get_researcher_service(request)
    
    task = await service.get_task(task_id)
    check_resource_ownership(user, task.owner_user_id)
    
    output = await service.get_output(task_id, after_seq=after_seq)
    return output
```

### 3.2 简化的 Request Schema

```python
# src/ainrf/api/schemas.py

class TaskCreateRequest(BaseModel):
    project_id: str
    workspace_id: str
    environment_id: str
    researcher_type: Literal["vanilla", "aris-researcher"]
    harness_engine: Literal["claude-code", "agent-sdk", "codex-app-server"]
    prompt: str
    skills: list[str] = []  # 仅当 researcher_type == "vanilla" 时有效
    mcp_servers: list[str] = []  # 未来扩展
```

**对比旧 API**：
- 删除了复杂的 `binding`、`runtime`、`profile` 字段
- 用户只需选择 `researcher_type` 和 `harness_engine`
- `skills` 仅在 vanilla 模式下可用

## 四、数据库设计

### 4.1 统一的任务表

```sql
-- 删除旧表
DROP TABLE IF EXISTS managed_tasks;
DROP TABLE IF EXISTS task_terminal_bindings;
DROP TABLE IF EXISTS task_takeover_leases;
DROP TABLE IF EXISTS task_harness_records;
DROP TABLE IF EXISTS task_harness_outputs;

-- 创建新的统一表
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    
    -- Researcher 配置
    researcher_type TEXT NOT NULL,
    harness_engine TEXT NOT NULL,
    user_skills TEXT,  -- JSON array
    user_mcp_servers TEXT,  -- JSON array
    
    -- 执行状态
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    
    -- 时间戳
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    
    -- 所有权
    owner_user_id TEXT NOT NULL,
    
    -- 执行结果
    exit_code INTEGER,
    error_summary TEXT
);

CREATE TABLE task_outputs (
    task_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);

-- 索引
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_owner ON tasks(owner_user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
```

### 4.2 权限表简化

保留基础的 `users` 和 `refresh_tokens` 表，删除：
- `project_collaborators` 表（第一版不支持项目隔离）
- `environment_access` 表（环境访问简化为所有用户可用）

## 五、前端设计

### 5.1 简化的任务创建表单

```typescript
// frontend/src/pages/tasks/TaskCreateForm.tsx

interface TaskFormData {
  projectId: string
  workspaceId: string
  environmentId: string
  researcherType: 'vanilla' | 'aris-researcher'  // 只有两个选择
  harnessEngine: 'claude-code' | 'agent-sdk' | 'codex-app-server'
  prompt: string
  skills?: string[]  // 仅当 researcherType === 'vanilla' 时显示
}

// UI 结构：
// 1. 选择 Researcher 类型（radio 单选）
//    - Vanilla: 空白研究员，可外挂 skills
//    - ARIS: 预装 ARIS skills
// 2. 选择执行引擎（dropdown）
// 3. 如果选了 Vanilla，显示 skills 多选框
// 4. 输入 prompt（textarea）
```

### 5.2 简化的任务详情页

```typescript
// frontend/src/pages/tasks/TaskDetail.tsx

// 删除的复杂显示：
// - binding 详情
// - runtime 详情
// - prompt layers

// 保留的核心显示：
// - 任务状态
// - 研究员类型 + 执行引擎
// - 输出流
// - 操作按钮（cancel、retry）
```

### 5.3 删除的前端文件

- `PromptEditor.tsx` - 删除复杂的 prompt 编辑器
- 部分 `useTaskMessages.ts` - 简化为直接使用 output stream
- `status.ts` 中的复杂状态映射 - 统一使用 TaskStatus

## 六、实施计划

### 阶段 1：搭建新架构（3 天）

**Task 1.1：创建 agentic_researcher 模块**
- 创建 `src/ainrf/agentic_researcher/` 目录
- 定义 `models.py`：AgenticResearcherType, AgenticResearcher, Task, TaskStatus
- 定义 `presets.py`：vanilla() 和 aris() 工厂函数

**Task 1.2：创建 harness_engine 模块**
- 创建 `src/ainrf/harness_engine/` 目录
- 定义 `base.py`：HarnessEngine 协议
- 定义 `context.py`：ExecutionContext, ExecutionHandle
- 定义 `events.py`：OutputEvent, EngineEvent

**Task 1.3：迁移执行引擎**
- 从 `task_harness/engines/` 迁移到 `harness_engine/engines/`
- 适配新的 HarnessEngine 协议
- 保持原有的启动逻辑

### 阶段 2：重写核心服务（4 天）

**Task 2.1：实现 AgenticResearcherService**
- 创建 `src/ainrf/agentic_researcher/service.py`
- 实现任务 CRUD：create_task, list_tasks, get_task, cancel_task, retry_task
- 实现输出管理：get_output, stream_output
- 初始化新的数据库 schema

**Task 2.2：重写 API routes**
- 重写 `src/ainrf/api/routes/tasks.py`
- 使用新的 AgenticResearcherService
- 实现三层权限检查

**Task 2.3：定义新的 API schemas**
- 更新 `src/ainrf/api/schemas.py`
- 定义 TaskCreateRequest, TaskResponse, TaskListResponse
- 删除旧的复杂 schema

### 阶段 3：清理旧代码（2 天）

**Task 3.1：删除旧任务系统**
- 删除 `src/ainrf/tasks/` 整个目录
- 删除 `task_harness/` 中的冗余文件
- 更新导入路径

**Task 3.2：清理数据库**
- 在 service initialize 中删除旧表
- 创建新的统一表
- 删除 project_collaborators 和 environment_access 相关逻辑

**Task 3.3：简化权限系统**
- 重写 `src/ainrf/auth/permissions.py`
- 删除复杂的协作者和环境访问检查
- 统一为三层权限模型

### 阶段 4：前端适配（3 天）

**Task 4.1：重写 TaskCreateForm**
- 简化为 researcher type + engine + prompt
- 动态显示 skills 选择（仅 vanilla 模式）
- 更新 API 调用

**Task 4.2：简化 TaskDetail 和 TaskList**
- 删除复杂的 binding/runtime 显示
- 保留核心的状态、输出、操作
- 更新 API 调用

**Task 4.3：清理前端文件**
- 删除 PromptEditor.tsx
- 简化 useTaskMessages.ts
- 统一 status 枚举

### 阶段 5：测试和文档（2 天）

**Task 5.1：端到端测试**
- 测试 vanilla researcher 创建和执行
- 测试 aris researcher 创建和执行
- 测试任务取消和重试
- 测试权限检查

**Task 5.2：更新文档**
- 更新 AGENTS.md 和 PROJECT_BASIS.md
- 编写迁移指南
- 更新 API 文档

**Task 5.3：代码审查和清理**
- 检查遗留的旧导入
- 清理未使用的代码
- 验证类型标注完整性

## 七、风险和缓解

### 7.1 数据迁移风险

**风险**：删除旧表会导致现有数据丢失

**缓解**：
- 项目明确没有生产数据，可以安全删除
- 如果有测试数据需要保留，先导出为 JSON
- 提供 migration script 用于数据格式转换（如果未来需要）

### 7.2 执行引擎兼容性

**风险**：从 task_harness 迁移到 harness_engine 可能破坏现有引擎

**缓解**：
- 保持引擎内部实现不变，只改外层抽象
- 增加单元测试覆盖每个引擎
- 分步迁移，先验证 claude-code 引擎

### 7.3 前端 API 破坏性变更

**风险**：API schema 变更导致前端功能失效

**缓解**：
- 前后端同步改造
- 先实现后端 API，用 curl/Postman 验证
- 再适配前端，确保端到端流程通畅

## 八、成功标准

重构完成后，系统应满足：

1. **用户视角**
   - 创建任务只需选择 researcher 类型和引擎，填写 prompt
   - 不需要理解 binding、runtime、profile 等内部概念
   - 任务列表和详情页清晰直观

2. **开发者视角**
   - 模块职责清晰：agentic_researcher（任务）、harness_engine（执行）、auth（权限）
   - 代码库减少约 30% 复杂度（删除双轨系统）
   - 新增功能时容易定位到正确的模块

3. **技术指标**
   - 所有 API 测试通过
   - 前端端到端测试通过
   - 类型检查无错误（ty check）
   - 代码格式通过（ruff format）

4. **文档完整性**
   - 更新 AGENTS.md 和 PROJECT_BASIS.md
   - 提供迁移指南（如果有遗留数据）
   - API 文档与实现一致

## 九、未来扩展

重构后的架构为以下扩展留出空间：

1. **更多 Researcher 预设**
   - `code-reviewer`：专注代码审查的研究员
   - `doc-writer`：专注文档编写的研究员
   - 用户可以自定义和保存 researcher 配置

2. **更多执行引擎**
   - `opencode`：本地 opencode 引擎

3. **细粒度权限**
   - 项目协作者（重新引入 project_collaborators）
   - 环境访问控制（重新引入 environment_access）
   - 基于角色的资源配额

4. **任务编排**
   - DAG 任务依赖（任务 A 完成后启动任务 B）
   - 并行任务（多个 researcher 协作）
   - 任务模板和批量创建

## 十、总结

本次重构通过引入清晰的两层架构（AgenticResearcher + HarnessEngine），彻底解决了当前系统的以下问题：

1. ✅ 统一任务系统，废弃双轨制
2. ✅ 简化用户心智模型，只需理解 researcher 类型和引擎
3. ✅ 清晰的模块边界，职责分离
4. ✅ 分层权限模型，逻辑清晰
5. ✅ 为未来扩展留出空间

预计开发周期 2 周，分 5 个阶段实施，每个阶段都可独立验证和交付。
