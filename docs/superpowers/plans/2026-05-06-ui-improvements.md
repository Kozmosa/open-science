# UI 改进实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现三个 UI 改进：通用 Modal 组件（含新建任务对话框关闭按钮）、default 工作空间目录迁移到 `~/.ainrf_workspaces/default/`、环境探测结果分组卡片式 Modal 展示。

**Architecture:** 提取可复用的 `Modal` 组件统一所有模态框行为（focus trap、Escape 关闭、backdrop 点击、进入/退出动画）。后端路径配置一处修改。环境探测详情使用独立 `EnvironmentDetectionModal` 组件，按功能分组渲染。

**Tech Stack:** React 19 + TypeScript + Tailwind CSS v4, Python 3.13 + pathlib

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `frontend/src/hooks/useFocusTrap.ts` | 新建 | Focus trap hook，管理 Tab 循环焦点 |
| `frontend/src/components/ui/Modal.tsx` | 新建 | 通用 Modal 组件：backdrop、动画、关闭按钮、标题栏 |
| `frontend/src/components/ui/index.ts` | 修改 | 导出 Modal 组件 |
| `frontend/src/pages/TasksPage.tsx` | 修改 | 替换 inline modal 为 `<Modal>` 组件 |
| `src/ainrf/runtime/paths.py` | 修改 | `default_workspace_dir` 改为 `~/.ainrf_workspaces/default/` |
| `frontend/src/components/environment/EnvironmentDetectionModal.tsx` | 新建 | 环境探测结果分组卡片式展示 Modal |
| `frontend/src/components/environment/index.ts` | 修改 | 导出 EnvironmentDetectionModal |
| `frontend/src/pages/EnvironmentsPage.tsx` | 修改 | 替换探测结果文本为链接，集成 EnvironmentDetectionModal |
| `frontend/src/i18n/messages.ts` | 修改 | 新增所有 i18n 键（中英文） |

---

### Task 1: useFocusTrap hook

**Files:**
- Create: `frontend/src/hooks/useFocusTrap.ts`
- Test: `frontend/src/hooks/useFocusTrap.test.ts` (可选，若项目无 hook 测试惯例则跳过)

**设计：** 基于 `TasksPage.tsx` 中现有 `trapDialogFocus` 回调逻辑，封装为可复用 hook。

- [ ] **Step 1: 创建 hook 文件**

```typescript
import { useCallback, useEffect, useRef } from 'react';

export function useFocusTrap<T extends HTMLElement = HTMLDivElement>(
  isActive: boolean
): React.RefObject<T | null> {
  const containerRef = useRef<T>(null);

  const trapFocus = useCallback((event: KeyboardEvent) => {
    if (event.key !== 'Tab' || !containerRef.current) {
      return;
    }

    const focusable = Array.from(
      containerRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
      )
    );
    if (focusable.length === 0) {
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }, []);

  useEffect(() => {
    if (!isActive) {
      return;
    }

    // Focus first focusable element on mount
    const timer = window.setTimeout(() => {
      const focusable = containerRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
      );
      focusable?.[0]?.focus();
    }, 0);

    document.addEventListener('keydown', trapFocus);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('keydown', trapFocus);
    };
  }, [isActive, trapFocus]);

  return containerRef;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/hooks/useFocusTrap.ts
git commit -m "$(cat <<'EOF'
feat: add useFocusTrap hook for modal focus management

Extracts the existing trapDialogFocus logic from TasksPage into a
reusable hook that auto-focuses the first focusable element and
cycles focus on Tab/Shift+Tab.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Modal 组件

**Files:**
- Create: `frontend/src/components/ui/Modal.tsx`
- Modify: `frontend/src/components/ui/index.ts`

**设计：** 通用 Modal 组件，包含：
- backdrop（半透明黑色遮罩）
- 居中 dialog 容器，支持多种尺寸
- 可选标题栏 + 关闭按钮（X 图标）
- Escape 键关闭、backdrop 点击关闭
- CSS transition 进入/退出动画
- 使用 `useFocusTrap` hook

- [ ] **Step 1: 创建 Modal 组件**

```tsx
import { X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useT } from '../../i18n';

const sizeClasses = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string | null;
  children: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showCloseButton?: boolean;
  closeOnBackdropClick?: boolean;
}

export function Modal({
  isOpen,
  onClose,
  title = null,
  children,
  size = 'md',
  showCloseButton = true,
  closeOnBackdropClick = true,
}: ModalProps) {
  const t = useT();
  const [isClosing, setIsClosing] = useState(false);
  const [shouldRender, setShouldRender] = useState(isOpen);
  const containerRef = useFocusTrap<HTMLDivElement>(shouldRender);

  useEffect(() => {
    if (isOpen) {
      setIsClosing(false);
      setShouldRender(true);
    } else if (shouldRender) {
      setIsClosing(true);
    }
  }, [isOpen, shouldRender]);

  const handleTransitionEnd = useCallback(() => {
    if (isClosing) {
      setShouldRender(false);
    }
  }, [isClosing]);

  const handleBackdropClick = useCallback(
    (event: React.MouseEvent) => {
      if (closeOnBackdropClick && event.target === event.currentTarget) {
        onClose();
      }
    },
    [closeOnBackdropClick, onClose]
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    },
    [onClose]
  );

  if (!shouldRender) {
    return null;
  }

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 transition-opacity duration-150 ${
        isClosing ? 'opacity-0' : 'opacity-100'
      }`}
      onClick={handleBackdropClick}
      onTransitionEnd={handleTransitionEnd}
    >
      <div
        className="fixed inset-0 bg-black/45"
        aria-hidden="true"
      />

      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? undefined}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={`relative max-h-[90vh] w-full overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl transition-transform transition-opacity duration-200 ease-out ${
          isClosing ? 'scale-96 opacity-0' : 'scale-100 opacity-100'
        } ${sizeClasses[size]}`}
      >
        {(title || showCloseButton) ? (
          <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
            {title ? (
              <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">{title}</h2>
            ) : (
              <span />
            )}
            {showCloseButton ? (
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
                aria-label={t('components.modal.close')}
              >
                <X size={18} />
              </button>
            ) : null}
          </div>
        ) : null}

        <div className={title || showCloseButton ? 'p-5 pt-0' : 'p-5'}>
          {children}
        </div>
      </div>
    </div>
  );
}
```

注意：`scale-96` 需要确认 Tailwind v4 是否支持。如果不支持，使用内联样式或添加自定义类：`--tw-scale-x: 0.96; --tw-scale-y: 0.96;`。在 Tailwind v4 中可以直接用 `scale-96` 或添加 `scale-[0.96]`。

- [ ] **Step 2: 导出 Modal 组件**

修改 `frontend/src/components/ui/index.ts`，添加：

```typescript
export { Modal } from './Modal';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/Modal.tsx frontend/src/components/ui/index.ts
git commit -m "$(cat <<'EOF'
feat: add reusable Modal component with animations

Includes backdrop, title bar, close button, focus trap,
Escape/click-outside dismissal, and enter/exit CSS transitions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: TasksPage 使用 Modal 组件

**Files:**
- Modify: `frontend/src/pages/TasksPage.tsx`

**设计：** 将现有的 inline modal 结构替换为 `<Modal>` 组件，保留所有现有 props 传递。

- [ ] **Step 1: 修改导入**

在 `TasksPage.tsx` 顶部添加：

```typescript
import { Modal } from '../components/ui';
```

删除 `trapDialogFocus` 回调函数（lines 163-188）——其逻辑已移至 `useFocusTrap` hook，由 `Modal` 内部使用。

- [ ] **Step 2: 替换 inline modal**

将 lines 297-333：

```tsx
{isCreateDialogOpen ? (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('pages.tasks.createTitle')}
      tabIndex={-1}
      onKeyDown={(event) => {
        trapDialogFocus(event);
        if (event.key === 'Escape') {
          closeCreateDialog();
        }
      }}
      className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 shadow-2xl"
    >
      <TaskCreateForm ... />
    </div>
  </div>
) : null}
```

替换为：

```tsx
<Modal
  isOpen={isCreateDialogOpen}
  onClose={closeCreateDialog}
  title={t('pages.tasks.createTitle')}
  size="lg"
>
  <TaskCreateForm
    key={`${effectiveEnvironmentId}:${draftResetVersion}`}
    workspaces={workspaces}
    environments={environments}
    selectedWorkspaceId={effectiveWorkspaceId}
    selectedEnvironmentId={effectiveEnvironmentId}
    selectedWorkspace={selectedWorkspace}
    selectedEnvironment={selectedEnvironment}
    draftDefaults={draftDefaults}
    researchAgentProfiles={settings.taskConfiguration.researchAgentProfiles}
    taskConfigurations={settings.taskConfiguration.taskConfigurations}
    availableSkills={availableSkills}
    isSubmitting={createMutation.isPending}
    createError={createError}
    onSelectWorkspace={setSelectedWorkspaceId}
    onSelectEnvironment={environmentSelection.onSelectEnvironment}
    onSubmit={(payload) => createMutation.mutate(payload)}
    onClose={closeCreateDialog}
  />
</Modal>
```

注意：原 inline modal 没有标题栏，`TaskCreateForm` 内部有自己的布局。添加 `title` 后会在顶部显示标题栏。如果设计不希望有标题栏（保持原外观），可以设置 `title={null}`，只通过 `showCloseButton` 显示关闭按钮。

**决策：** 由于原设计没有标题栏，改为 `title={null}` 保持外观一致，只添加关闭按钮：

```tsx
<Modal
  isOpen={isCreateDialogOpen}
  onClose={closeCreateDialog}
  title={null}
  size="lg"
>
  ...
</Modal>
```

这样关闭按钮会显示在右上角（因为 `showCloseButton` 默认为 `true`），但没有标题栏。

- [ ] **Step 3: 运行类型检查**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 无错误，exit 0。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TasksPage.tsx
git commit -m "$(cat <<'EOF'
feat: replace inline task dialog with reusable Modal component

Adds a close button (X) to the new-task dialog while preserving
the existing focus trap and Escape-to-close behavior.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 后端 default 工作空间目录迁移

**Files:**
- Modify: `src/ainrf/runtime/paths.py`
- Test: `tests/test_runtime_paths.py`

**设计：** 将 `default_workspace_dir` 从 `{cwd}/workspace/default` 改为 `~/.ainrf_workspaces/default/`。

- [ ] **Step 1: 修改路径配置**

修改 `src/ainrf/runtime/paths.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePathConfig:
    startup_cwd: Path

    @property
    def workspace_root(self) -> Path:
        return self.startup_cwd / "workspace"

    @property
    def default_workspace_dir(self) -> Path:
        return Path.home() / ".ainrf_workspaces" / "default"

    def ensure_default_workspace_dir(self) -> Path:
        path = self.default_workspace_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


def build_runtime_path_config(startup_cwd: Path | None = None) -> RuntimePathConfig:
    return RuntimePathConfig(startup_cwd=(startup_cwd or Path.cwd()).resolve())
```

变更：`default_workspace_dir` 返回 `Path.home() / ".ainrf_workspaces" / "default"`。
`workspace_root` 保持原值（仍指向 `{cwd}/workspace`，供其他用途使用）。

- [ ] **Step 2: 更新测试**

读取 `tests/test_runtime_paths.py` 并更新相关断言：

```python
# tests/test_runtime_paths.py
# 找到测试 default_workspace_dir 的断言，修改为：

expected = Path.home() / ".ainrf_workspaces" / "default"
assert config.default_workspace_dir == expected
```

- [ ] **Step 3: 运行测试**

```bash
uv run pytest tests/test_runtime_paths.py -v
```

Expected: 全部通过。

```bash
uv run pytest tests/test_api_health.py tests/test_api_environments.py -v
```

Expected: 全部通过（验证 health/environment API 不受路径变更影响）。

- [ ] **Step 4: Commit**

```bash
git add src/ainrf/runtime/paths.py tests/test_runtime_paths.py
git commit -m "$(cat <<'EOF'
feat: move default workspace dir to ~/.ainrf_workspaces/default/

Changes the seed workspace default_workdir from {cwd}/workspace/default
to ~/.ainrf_workspaces/default/ for better separation of runtime data
from project source.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: EnvironmentDetectionModal 组件

**Files:**
- Create: `frontend/src/components/environment/EnvironmentDetectionModal.tsx`
- Modify: `frontend/src/components/environment/index.ts`

**设计：** 接收 `EnvironmentDetection` 数据，按 6 个分组渲染卡片式布局。

- [ ] **Step 1: 创建组件**

```tsx
import { AlertTriangle, CheckCircle2, Cpu, Globe, HardDrive, Package, Terminal, Variable, XCircle } from 'lucide-react';
import { Modal } from '../ui';
import { useT } from '../../i18n';
import type { EnvironmentDetection } from '../../types';
import StatusDot from '../ui/StatusDot';

interface EnvironmentDetectionModalProps {
  detection: EnvironmentDetection;
  environmentName: string;
  isOpen: boolean;
  onClose: () => void;
}

function StatusBadge({ available, version }: { available: boolean; version: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <StatusDot status={available ? 'success' : 'error'} />
      <span className={available ? 'text-[var(--text)]' : 'text-[var(--text-secondary)]'}>
        {available ? '可用' : '不可用'}
      </span>
      {version ? (
        <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs text-[var(--text-secondary)]">{version}</code>
      ) : null}
    </div>
  );
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
      <span className="text-sm text-[var(--text)]">{children}</span>
    </div>
  );
}

function SectionCard({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="mb-3 flex items-center gap-2 border-b border-[var(--border)] pb-2">
        <Icon size={16} className="text-[var(--apple-blue)]" />
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-secondary)]">{title}</span>
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export function EnvironmentDetectionModal({
  detection,
  environmentName,
  isOpen,
  onClose,
}: EnvironmentDetectionModalProps) {
  const t = useT();

  const statusConfig = {
    success: { color: 'bg-emerald-500', label: '成功', icon: CheckCircle2 },
    partial: { color: 'bg-amber-500', label: '部分成功', icon: AlertTriangle },
    failed: { color: 'bg-red-500', label: '失败', icon: XCircle },
  };
  const status = statusConfig[detection.status];

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`${environmentName} · 环境探测结果`} size="lg">
      {/* 状态条 */}
      <div className={`mb-4 flex items-center gap-2 rounded-lg ${status.color}/10 p-3`}>
        <status.icon size={18} className={status.color.replace('bg-', 'text-')} />
        <span className={`font-medium ${status.color.replace('bg-', 'text-')}`}>{status.label}</span>
        <span className="text-sm text-[var(--text-secondary)]">· {detection.summary}</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {/* 基本信息 */}
        <SectionCard title="基本信息" icon={Globe}>
          <InfoRow label="SSH">
            <StatusBadge available={detection.ssh_ok} version={null} />
          </InfoRow>
          <InfoRow label="主机名">{detection.hostname ?? '—'}</InfoRow>
          <InfoRow label="操作系统">{detection.os_info ?? '—'}</InfoRow>
          <InfoRow label="架构">{detection.arch ?? '—'}</InfoRow>
          <InfoRow label="工作目录">
            <StatusBadge
              available={detection.workdir_exists ?? false}
              version={null}
            />
          </InfoRow>
        </SectionCard>

        {/* Python 工具链 */}
        <SectionCard title="Python 工具链" icon={Package}>
          <InfoRow label="Python">
            <StatusBadge available={detection.python.available} version={detection.python.version} />
          </InfoRow>
          <InfoRow label="Conda">
            <StatusBadge available={detection.conda.available} version={detection.conda.version} />
          </InfoRow>
          <InfoRow label="uv">
            <StatusBadge available={detection.uv.available} version={detection.uv.version} />
          </InfoRow>
          <InfoRow label="pixi">
            <StatusBadge available={detection.pixi.available} version={detection.pixi.version} />
          </InfoRow>
        </SectionCard>

        {/* 开发工具 */}
        <SectionCard title="开发工具" icon={Terminal}>
          <InfoRow label="Code Server">
            <StatusBadge available={detection.code_server.available} version={detection.code_server.version} />
          </InfoRow>
          <InfoRow label="Claude CLI">
            <StatusBadge available={detection.claude_cli.available} version={detection.claude_cli.version} />
          </InfoRow>
        </SectionCard>

        {/* AI/ML 环境 */}
        <SectionCard title="AI / ML 环境" icon={Cpu}>
          <InfoRow label="PyTorch">
            <StatusBadge available={detection.torch.available} version={detection.torch.version} />
          </InfoRow>
          <InfoRow label="CUDA">
            <StatusBadge available={detection.cuda.available} version={detection.cuda.version} />
          </InfoRow>
        </SectionCard>

        {/* GPU 信息 */}
        <SectionCard title="GPU 信息" icon={HardDrive}>
          <InfoRow label="GPU 数量">{detection.gpu_count}</InfoRow>
          <InfoRow label="GPU 型号">
            {detection.gpu_models.length > 0 ? detection.gpu_models.join(', ') : '—'}
          </InfoRow>
        </SectionCard>

        {/* 环境变量 */}
        <SectionCard title="环境变量" icon={Variable}>
          <InfoRow label="Anthropic">
            <span
              className={`text-sm ${
                detection.anthropic_env === 'present'
                  ? 'text-emerald-600'
                  : detection.anthropic_env === 'missing'
                    ? 'text-red-500'
                    : 'text-[var(--text-secondary)]'
              }`}
            >
              {detection.anthropic_env === 'present'
                ? '已配置'
                : detection.anthropic_env === 'missing'
                  ? '未配置'
                  : '未知'}
            </span>
          </InfoRow>
        </SectionCard>
      </div>

      {/* 错误与警告 */}
      {detection.errors.length > 0 ? (
        <div className="mt-4 space-y-2">
          {detection.errors.map((error, index) => (
            <div
              key={index}
              className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
            >
              <XCircle size={16} className="mr-1.5 inline" />{error}
            </div>
          ))}
        </div>
      ) : null}

      {detection.warnings.length > 0 ? (
        <div className="mt-4 space-y-2">
          {detection.warnings.map((warning, index) => (
            <div
              key={index}
              className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
            >
              <AlertTriangle size={16} className="mr-1.5 inline" />{warning}
            </div>
          ))}
        </div>
      ) : null}
    </Modal>
  );
}
```

注意：
- `StatusDot` 组件需要确认其实际路径和 props。根据探索结果，它在 `frontend/src/components/ui/StatusDot.tsx` 或类似位置。
- 如果 `StatusDot` 不接受 `status` prop 或有不同的接口，需要调整。
- 颜色类名使用了 Tailwind 标准色值（`emerald`、`amber`、`red`），需确认项目中是否可用。如果项目只用 CSS 变量，需要改为对应的 CSS variable。

- [ ] **Step 2: 导出组件**

修改 `frontend/src/components/environment/index.ts`（如果不存在则新建），添加：

```typescript
export { EnvironmentDetectionModal } from './EnvironmentDetectionModal';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/environment/EnvironmentDetectionModal.tsx frontend/src/components/environment/index.ts
git commit -m "$(cat <<'EOF'
feat: add EnvironmentDetectionModal component

Grouped card layout showing environment detection results:
basic info, Python toolchain, dev tools, AI/ML, GPU, env vars.
Includes status badges, errors, and warnings display.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: EnvironmentsPage 集成 EnvironmentDetectionModal

**Files:**
- Modify: `frontend/src/pages/EnvironmentsPage.tsx`

**设计：** 将探测结果列的文本替换为可点击链接，点击打开 EnvironmentDetectionModal。

- [ ] **Step 1: 添加导入和 state**

在 `EnvironmentsPage.tsx` 顶部添加：

```typescript
import { EnvironmentDetectionModal } from '../components/environment';
```

在组件 state 区域（line 546 附近）添加：

```typescript
const [selectedDetectionEnvironmentId, setSelectedDetectionEnvironmentId] = useState<string | null>(null);
```

- [ ] **Step 2: 替换探测结果展示**

将 lines 850-866：

```tsx
<td className="px-4 py-4">
  {detection ? (
    <div className="space-y-1">
      <div className="text-sm font-medium text-[var(--text)]">
        {detectionStatusLabels[detection.status] ?? detection.status} ·{' '}
        {detection.summary}
      </div>
      <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
        {t('pages.environments.detectedAt')}{' '}
        {formatTimestamp(detection.detected_at, locale, t('common.never'))}
      </div>
    </div>
  ) : (
    <span className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
      {t('pages.environments.notDetected')}
    </span>
  )}
</td>
```

替换为：

```tsx
<td className="px-4 py-4">
  {detection ? (
    <div className="space-y-1">
      <button
        type="button"
        className="text-sm font-medium text-[var(--apple-blue)] hover:underline"
        onClick={() => setSelectedDetectionEnvironmentId(environment.id)}
      >
        {detectionStatusLabels[detection.status] ?? detection.status}
      </button>
      <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
        {t('pages.environments.detectedAt')}{' '}
        {formatTimestamp(detection.detected_at, locale, t('common.never'))}
      </div>
    </div>
  ) : (
    <span className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
      {t('pages.environments.notDetected')}
    </span>
  )}
</td>
```

- [ ] **Step 3: 添加 Modal 渲染**

在 `EnvironmentsPage` 组件的 return 语句末尾（`</div>` 关闭标签之前），添加：

```tsx
{
  selectedDetectionEnvironmentId !== null ? (
    (() => {
      const env = environments.find(
        (e) => e.id === selectedDetectionEnvironmentId
      );
      if (!env?.latest_detection) return null;
      return (
        <EnvironmentDetectionModal
          detection={env.latest_detection}
          environmentName={env.display_name}
          isOpen={true}
          onClose={() => setSelectedDetectionEnvironmentId(null)}
        />
      );
    })()
  ) : null
}
```

- [ ] **Step 4: 运行类型检查**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 无错误，exit 0。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/EnvironmentsPage.tsx
git commit -m "$(cat <<'EOF'
feat: add environment detection detail modal to environments page

Replaces the detection summary text with a clickable link that
opens the grouped-card EnvironmentDetectionModal.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: i18n 翻译

**Files:**
- Modify: `frontend/src/i18n/messages.ts`

**设计：** 添加所有新组件所需的翻译键。

- [ ] **Step 1: 读取现有 messages.ts 结构**

```bash
cat frontend/src/i18n/messages.ts | head -50
```

了解 `en` 和 `zh` 对象的结构，找到合适的插入位置。

- [ ] **Step 2: 添加翻译键**

在 `en` 对象中添加：

```typescript
components: {
  // ... existing components
  modal: {
    close: 'Close',
  },
  environmentDetectionModal: {
    title: '{name} · Environment Detection',
    groups: {
      basicInfo: 'Basic Info',
      pythonToolchain: 'Python Toolchain',
      devTools: 'Dev Tools',
      aiMl: 'AI / ML',
      gpu: 'GPU Info',
      envVars: 'Environment Variables',
    },
    labels: {
      ssh: 'SSH',
      hostname: 'Hostname',
      os: 'OS',
      arch: 'Architecture',
      workdir: 'Workdir',
      python: 'Python',
      conda: 'Conda',
      uv: 'uv',
      pixi: 'pixi',
      codeServer: 'Code Server',
      claudeCli: 'Claude CLI',
      torch: 'PyTorch',
      cuda: 'CUDA',
      gpuCount: 'GPU Count',
      gpuModels: 'GPU Models',
      anthropic: 'Anthropic',
    },
    status: {
      available: 'Available',
      unavailable: 'Unavailable',
      present: 'Present',
      missing: 'Missing',
      unknown: 'Unknown',
    },
  },
},
```

在 `zh` 对象中添加对应的翻译：

```typescript
components: {
  // ... existing components
  modal: {
    close: '关闭',
  },
  environmentDetectionModal: {
    title: '{name} · 环境探测结果',
    groups: {
      basicInfo: '基本信息',
      pythonToolchain: 'Python 工具链',
      devTools: '开发工具',
      aiMl: 'AI / ML 环境',
      gpu: 'GPU 信息',
      envVars: '环境变量',
    },
    labels: {
      ssh: 'SSH',
      hostname: '主机名',
      os: '操作系统',
      arch: '架构',
      workdir: '工作目录',
      python: 'Python',
      conda: 'Conda',
      uv: 'uv',
      pixi: 'pixi',
      codeServer: 'Code Server',
      claudeCli: 'Claude CLI',
      torch: 'PyTorch',
      cuda: 'CUDA',
      gpuCount: 'GPU 数量',
      gpuModels: 'GPU 型号',
      anthropic: 'Anthropic',
    },
    status: {
      available: '可用',
      unavailable: '不可用',
      present: '已配置',
      missing: '未配置',
      unknown: '未知',
    },
  },
},
```

- [ ] **Step 3: 更新组件使用翻译**

回到 `EnvironmentDetectionModal.tsx`，将硬编码的中文文本替换为 `t()` 调用。例如：

```tsx
<SectionCard title={t('components.environmentDetectionModal.groups.basicInfo')} icon={Globe}>
  <InfoRow label={t('components.environmentDetectionModal.labels.ssh')}>...</InfoRow>
```

状态文本也替换：

```tsx
{available ? t('components.environmentDetectionModal.status.available') : t('components.environmentDetectionModal.status.unavailable')}
```

- [ ] **Step 4: 运行类型检查**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 无错误，exit 0。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/messages.ts frontend/src/components/environment/EnvironmentDetectionModal.tsx
git commit -m "$(cat <<'EOF'
i18n: add translations for Modal and EnvironmentDetectionModal

Adds en/zh keys for modal close button and all environment
detection modal labels, groups, and status values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 最终验证

- [ ] **Step 1: 前端类型检查**

```bash
cd frontend && node_modules/.bin/tsc -b
```

Expected: 无错误，exit 0。

- [ ] **Step 2: 前端测试**

```bash
cd frontend && npm run test:run
```

Expected: 无新失败（或全部通过，如果项目有前端测试）。

- [ ] **Step 3: Python 测试**

```bash
uv run pytest tests/test_runtime_paths.py tests/test_api_health.py tests/test_api_environments.py -v
```

Expected: 全部通过（runtime_paths 测试验证新路径，health/environment 测试验证 API 不受影响）。

- [ ] **Step 4: 代码格式检查**

```bash
uv run ruff check . --select=E,W,F
```

```bash
cd frontend && npx eslint src/ --ext .ts,.tsx 2>&1 | head -20 || true
```

（如果项目没有配置 ESLint，跳过此步。）

- [ ] **Step 5: Commit（如需要修复格式问题）**

如有格式修复：

```bash
uv run ruff check --fix .
cd frontend && node_modules/.bin/tsc -b
git commit -am "chore: fix formatting"
```

---

## 自审查

### 1. Spec 覆盖检查

| Spec 需求 | 对应 Task |
|---|---|
| 通用 Modal 组件 | Task 2 |
| Focus trap hook | Task 1 |
| 新建任务对话框关闭按钮 | Task 3 |
| default 工作空间目录改为 ~/.ainrf_workspaces/default/ | Task 4 |
| 环境探测结果分组卡片 Modal | Task 5 |
| EnvironmentsPage 集成链接+Modal | Task 6 |
| i18n 翻译 | Task 7 |
| CSS 动画（进入/退出） | Task 2（Modal 组件） |

全部覆盖，无遗漏。

### 2. Placeholder 扫描

- ✅ 无 "TBD", "TODO", "implement later"
- ✅ 无 "Add appropriate error handling" 等模糊描述
- ✅ 每个任务包含完整代码
- ✅ 每个任务包含具体命令和预期输出

### 3. 类型一致性

- ✅ `useFocusTrap` 返回 `RefObject<T | null>`，与 React 19 `useRef` 类型一致
- ✅ `ModalProps` 接口在 Task 2 定义，Task 3/5/6 使用方式一致
- ✅ `EnvironmentDetectionModalProps` 使用 `EnvironmentDetection` 类型，与 `types/index.ts` 一致
