# UI 改进设计文档

## 概述

本次改动包含三个独立但同在前端范围内的 UI 改进需求：

1. 新建任务对话框右上角添加关闭按钮
2. default 工作空间的根目录改为 `~/.ainrf_workspaces/default/`（后端自动创建）
3. 环境探测结果展示优化：长文本改为"成功"/"失败"超链接，点击打开模态框展示分组卡片式详细信息

## 方案选择

采用**方案 C（完整重构 + 动画）**：
- 提取通用 `Modal` 组件，统一所有模态框行为（focus trap、Escape 关闭、backdrop 点击关闭、进入/退出动画）
- 环境探测详情使用独立可复用组件 `EnvironmentDetectionModal`
- CSS transition 实现动画，不引入额外依赖

## 1. 通用 Modal 组件

### 文件

`frontend/src/components/ui/Modal.tsx`

### Props

| 属性 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `isOpen` | `boolean` | — | 控制显隐 |
| `onClose` | `() => void` | — | 关闭回调 |
| `title` | `string \| null` | `null` | 标题（可选） |
| `children` | `ReactNode` | — | 内容 |
| `size` | `'sm' \| 'md' \| 'lg' \| 'xl'` | `'md'` | 宽度预设 |
| `showCloseButton` | `boolean` | `true` | 是否显示右上角 X 按钮 |
| `closeOnBackdropClick` | `boolean` | `true` | 点击 backdrop 是否关闭 |

### 内部实现

- Backdrop：`fixed inset-0 z-50 bg-black/45`
- Dialog 容器：`z-50 flex items-center justify-center p-4`
- Dialog 内容：`rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl`
- Focus trap：封装为 hook `useFocusTrap`，基于现有 `trapDialogFocus` 逻辑
- Escape 键关闭：监听 `keydown`
- 关闭按钮：`lucide-react` 的 `X` 图标，位于标题栏右侧

### 动画

CSS transition，不引入动画库：

- **进入**：
  - backdrop：`opacity 0 → 1`，150ms
  - dialog：`scale(0.96) opacity-0 → scale(1) opacity-100`，200ms ease-out
- **退出**：
  - 反向动画，150ms
- 控制方式：React state `isClosing` + `onTransitionEnd`，退出动画完成后从 DOM 移除

### Hook

`frontend/src/hooks/useFocusTrap.ts`

接收一个 `containerRef: RefObject<HTMLElement>`，在 mount 时自动 focus 第一个可聚焦元素，监听 Tab/Shift+Tab 实现循环焦点。

## 2. 新建任务对话框关闭按钮

### 改动点

- `TasksPage.tsx` 中的 inline modal 逻辑替换为 `<Modal>` 组件
- `showCloseButton={true}`（默认），自动获得右上角 X 按钮
- 关闭行为与现有 Escape 键行为一致：调用 `closeCreateDialog`，关闭后将焦点恢复至"新建任务"按钮

### 代码变更

```tsx
// TasksPage.tsx 中替换以下 inline 结构：
{isCreateDialogOpen ? (
  <div className="fixed inset-0 z-50 ...">...</div>
) : null}

// 替换为：
<Modal
  isOpen={isCreateDialogOpen}
  onClose={closeCreateDialog}
  title={t('pages.tasks.createTitle')}
  size="xl"
>
  <TaskCreateForm ... />
</Modal>
```

## 3. Default 工作空间目录

### 需求

default 工作空间（seed workspace）的根目录从 `{cwd}/workspace/default` 改为 `~/.ainrf_workspaces/default/`，后端在初始化时自动创建。

### 后端改动

**文件：** `src/ainrf/runtime/paths.py`

修改 `RuntimePathConfig.default_workspace_dir` 属性：

```python
@property
def default_workspace_dir(self) -> Path:
    return Path.home() / ".ainrf_workspaces" / "default"
```

`ensure_default_workspace_dir()` 方法保持不变（`mkdir(parents=True, exist_ok=True)`），路径变更后自动在新位置创建目录。

**文件：** `src/ainrf/workspaces/service.py`

`_build_seed_workspace()` 方法中 `default_workdir_path` 的获取逻辑不需要改动，因为 `self._default_workspace_dir` 已由 `RuntimePathConfig` 提供正确路径。

### 数据迁移

- 现有安装：若已有 `{cwd}/workspace/default` 目录且包含数据，本次改动仅影响新创建的文件。现有工作空间记录中的 `default_workdir` 字段保持原值。
- 新安装：seed workspace 的 `default_workdir` 自动指向 `~/.ainrf_workspaces/default/`。

## 4. 环境探测结果 Modal

### 文件

`frontend/src/components/environment/EnvironmentDetectionModal.tsx`

### Props

```ts
interface EnvironmentDetectionModalProps {
  detection: EnvironmentDetection;
  environmentName: string;
  isOpen: boolean;
  onClose: () => void;
}
```

### 分组卡片布局

共 6 个分组，每组用卡片/分区包装：

| 分组 | 键 | 包含字段 |
|---|---|---|
| 基本信息 | `basicInfo` | ssh_ok, hostname, os_info, arch, workdir_exists |
| Python 工具链 | `pythonToolchain` | python, conda, uv, pixi |
| 开发工具 | `devTools` | code_server, claude_cli |
| AI/ML 环境 | `aiMl` | torch, cuda |
| GPU 信息 | `gpu` | gpu_models, gpu_count |
| 环境变量 | `envVars` | anthropic_env |

### 每组内部布局

- 组标题：小字大写 + 底部细线分隔
- 每行：左侧标签（`text-secondary`，固定宽度）+ 右侧值（`text`）
- 布尔/状态值：彩色 `StatusDot`（已有组件）
  - 可用/成功：`--success`（绿色）
  - 不可用/失败：`--error`（红色）
- 版本号：`<code>` 标签
- 路径：`<code>` 标签，过长时 `truncate`

### 整体状态条

Modal 顶部根据 `detection.status` 显示彩色状态条：

- `success` → 绿色
- `partial` → 橙色
- `failed` → 红色

### 错误与警告

- `errors.length > 0` → 底部红色 Alert 列表
- `warnings.length > 0` → 底部橙色 Alert 列表

### 父组件改动

**文件：** `frontend/src/pages/EnvironmentsPage.tsx`

- 新增 state：`selectedDetectionEnvironmentId: string | null`
- 探测结果列文本替换为超链接：
  ```tsx
  <button
    className="text-sm font-medium text-[var(--apple-blue)] hover:underline"
    onClick={() => setSelectedDetectionEnvironmentId(environment.id)}
  >
    {detectionStatusLabels[detection.status]}
  </button>
  ```
- 新增 `<EnvironmentDetectionModal>` 渲染（条件：`selectedDetectionEnvironmentId !== null`）

## 5. i18n 新增翻译键

**文件：** `frontend/src/i18n/messages.ts`

新增以下键（中英文）：

- `components.modal.close` — 关闭按钮 aria-label
- `components.environmentDetectionModal.title` — Modal 标题模板
- `components.environmentDetectionModal.groups.basicInfo`
- `components.environmentDetectionModal.groups.pythonToolchain`
- `components.environmentDetectionModal.groups.devTools`
- `components.environmentDetectionModal.groups.aiMl`
- `components.environmentDetectionModal.groups.gpu`
- `components.environmentDetectionModal.groups.envVars`
- `components.environmentDetectionModal.labels.ssh` 等（每个字段一个标签键）

## 6. 文件变更清单

| 操作 | 文件路径 |
|---|---|
| 新增 | `frontend/src/components/ui/Modal.tsx` |
| 新增 | `frontend/src/hooks/useFocusTrap.ts` |
| 新增 | `frontend/src/components/environment/EnvironmentDetectionModal.tsx` |
| 修改 | `frontend/src/pages/TasksPage.tsx` |
| 修改 | `frontend/src/pages/EnvironmentsPage.tsx` |
| 修改 | `src/ainrf/runtime/paths.py` |
| 修改 | `frontend/src/i18n/messages.ts` |

## 7. 测试考虑

- `Modal` 组件：focus trap 行为、Escape 关闭、backdrop 点击关闭
- `EnvironmentDetectionModal`：各分组正确渲染、状态颜色正确
- 后端：路径变更后 `ensure_default_workspace_dir()` 正确创建目录
