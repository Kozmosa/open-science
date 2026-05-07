# Project Canvas 功能设计文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 为 AINRF 添加 Project 管理页面，所有 Task 必须绑定到 Project，Project 详情页以自由画布展示 Task 之间的线性/分支关系图。

**Architecture:** 后端使用独立的 `TaskEdge` 表存储 Task 之间的 DAG 关系；前端新增 `/projects` 路由，使用 React Flow (`@xyflow/react`) 渲染可拖动画布，dagre 自动布局，localStorage 持久化用户调整后的位置。

**Tech Stack:** React 19 + TypeScript + Tailwind CSS v4, `@xyflow/react`, `dagre`, FastAPI + Python 3.13

---

## 1. 数据模型

### 1.1 TaskEdge（新增）

```python
@dataclass(slots=True)
class TaskEdge:
    edge_id: str          # uuid
    project_id: str
    source_task_id: str
    target_task_id: str
    created_at: datetime
```

### 1.2 现有模型变更

- `TaskCreateRequest.project_id`: 从 `Optional` 改为 **required**
- 已有 `project_id` 为空的 Task 在初始化时自动归属到 `default` project

---

## 2. 后端 API

### 2.1 新增 TaskHarnessService 方法

| Method | Signature | Description |
|--------|-----------|-------------|
| `list_project_tasks` | `(project_id: str) → list[TaskListItem]` | 按 project 过滤 task |
| `get_task_edges` | `(project_id: str) → list[TaskEdge]` | 获取 project 下所有 edge |
| `create_task_edge` | `(project_id, source, target) → TaskEdge` | 创建 edge |
| `delete_task_edge` | `(edge_id: str) → None` | 删除 edge |
| `create_task` | 增加 `auto_connect: bool = False` | 为 true 时自动连接到最后创建的 task |

### 2.2 新增/修改 API 路由

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects/{project_id}/tasks` | 列出 project 下所有 tasks |
| `GET` | `/projects/{project_id}/task-edges` | 列出 project 下所有 edges |
| `POST` | `/projects/{project_id}/task-edges` | 创建 edge |
| `DELETE` | `/task-edges/{edge_id}` | 删除 edge |
| `POST` | `/tasks` | `project_id` 改为必填 |

---

## 3. 前端架构

### 3.1 路由与导航

- 新增路由：`/projects`（lazy-loaded `ProjectsPage`）
- 导航顺序调整为：**Projects** → Terminal → Tasks → Workspaces → Workspace Browser → Environments → Resources → Settings
- `defaultRoutePathById` 新增 `projects: '/projects'`

### 3.2 ProjectsPage 布局

与 TasksPage 类似的左右分栏：

```
┌─────────────────────────────────────────────┐
│ Project Sidebar    │  Canvas Detail         │
│ (可拖拽调整宽度)    │  (ReactFlowProvider)    │
│ 260-520px          │                        │
│                    │  ┌─────────────────┐   │
│ - Project 列表      │  │ React Flow      │   │
│ - 新建按钮          │  │ Canvas          │   │
│ - 搜索/过滤         │  │                 │   │
│                    │  │ [task]──→[task] │   │
│                    │  │    ↓            │   │
│                    │  │  [task]         │   │
│                    │  └─────────────────┘   │
└─────────────────────────────────────────────┘
```

### 3.3 组件分解

| Component | 职责 |
|-----------|------|
| `ProjectsPage` | 状态管理（选中 project、sidebar 宽度）、数据转换（Task ↔ React Flow node） |
| `ProjectSidebar` | Project 列表、搜索、新建/删除 project 按钮 |
| `ProjectCanvas` | React Flow 画布封装（nodes、edges、layout、事件处理） |
| `TaskNode` | 自定义 React Flow Node（task 标题、状态 dot、环境信息） |
| `TaskDetailModal` | 复用现有 `Modal` + `TaskDetail` |

---

## 4. 画布组件设计

### 4.1 TaskNode

```tsx
function TaskNode({ data, selected }: NodeProps<TaskNodeData>) {
  const { task } = data;
  return (
    <div className={`rounded-xl border p-3 min-w-[180px] shadow-sm transition
      ${selected ? 'border-[var(--apple-blue)] ring-2' : 'border-[var(--border)]'}`}>
      <div className="flex items-center gap-2 mb-1">
        <StatusDot status={task.status} />
        <span className="text-sm font-medium truncate">{task.title}</span>
      </div>
      <div className="text-[11px] text-[var(--text-secondary)]">
        {task.environment_summary.alias} · {formatTime(task.created_at)}
      </div>
    </div>
  );
}
```

- **Source handle**: 右侧 (`Position.Right`) — 出边
- **Target handle**: 左侧 (`Position.Left`) — 入边
- 强制从左到右的视觉流向

### 4.2 Edge 样式

- React Flow 默认 `Bezier` edge，带箭头标记
- 默认颜色 `var(--border)`，选中时 `var(--apple-blue)`
- 目标 task 为 running 状态时 edge 可添加动画效果（Future）

### 4.3 自动布局

使用 `dagre` (`dagre.graphlib.Graph`)：

```typescript
function layoutDagre(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 80, ranksep: 120 });
  // add nodes/edges, run layout, return computed positions
}
```

触发时机：初始加载、新增 task 后、点击"Reset Layout"

---

## 5. 数据流与交互

### 5.1 localStorage 布局持久化

```typescript
const LAYOUT_KEY = (projectId: string) => `ainrf:project-layout:${projectId}`;

// 节点拖拽结束时保存位置
function onNodeDragStop(_event: MouseEvent, node: Node) {
  const positions = reactFlowInstance.getNodes().map(n => ({ id: n.id, x: n.x, y: n.y }));
  localStorage.setItem(LAYOUT_KEY(projectId), JSON.stringify(positions));
}

// 初始加载时恢复或自动布局
function restoreOrLayout(nodes: Node[], edges: Edge[]): Node[] {
  const saved = localStorage.getItem(LAYOUT_KEY(projectId));
  if (saved) {
    const positions = JSON.parse(saved);
    return nodes.map(n => {
      const p = positions.find((x: {id: string}) => x.id === n.id);
      return p ? { ...n, position: p } : n;
    });
  }
  return layoutDagre(nodes, edges);
}
```

### 5.2 TasksPage "New Task" 对话框变更

- 新增 **Project selector** 下拉框（位于 Workspace/Environment 选择器上方）
- 默认值：上次使用的 project（从 settings 或上下文推断）
- 选项末尾："Create new project..."
- 选择新建 project 时展开内联名称输入框，提交时同步创建 project
- `project_id` 变为必填字段

### 5.3 画布工具栏

```
[ + New Task ] [ Reset Layout ] [ Fit View ]
```

- **New Task**: 打开 `TaskCreateForm` Modal，`project_id` 锁定为当前 project
- **Reset Layout**: 清除 localStorage 覆盖，重新运行 dagre 布局
- **Fit View**: 调用 React Flow `fitView()`

### 5.4 Edge 生命周期（V1）

- 创建 task 时自动创建 edge（最后创建的 task → 新 task）
- 删除 task 时级联删除相关 edges
- **V1 不支持手动创建/删除 edge**（仅通过 task 创建隐式生成）
- Future: 支持从 source handle 拖拽到 target handle 手动创建连接

---

## 6. 测试策略

### 6.1 后端测试

- `tests/test_task_edges.py` — Edge CRUD、auto-connect 行为、级联删除
- 更新 `tests/test_api_tasks.py` — 验证 `project_id` 必填

### 6.2 前端测试

- `ProjectsPage.test.tsx` — project 列表渲染、选择、sidebar 调整
- `ProjectCanvas.test.tsx` — React Flow 画布渲染 nodes/edges、node 点击打开 modal
- `TaskNode.test.tsx` — node 正确渲染 task 数据

### 6.3 集成测试

- 创建 project → 从画布创建 task → 验证 node 出现 → 点击 node → modal 展示 task detail

---

## 7. 边界情况与注意事项

1. **空 project**: 画布为空时显示占位提示（"Click 'New Task' to get started"）
2. **孤立 task**: 没有 edge 的 task 仍然显示为独立 node
3. **循环检测**: dagre 不支持循环图，如果未来支持手动 edge 编辑需要添加 DAG 验证
4. **大量 task**: 50+ nodes 时性能测试，必要时启用 React Flow `onlyRenderVisibleElements`
5. **任务详情 Modal**: 复用现有 `TaskDetail` 组件，保持与 TasksPage 一致的体验
6. **i18n**: 所有新增文案通过 `useT()` 支持中英文
