import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowLeft, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { updateTask } from '@/shared/api';
import { useT } from '@/shared/i18n';
import { taskStatusClassName, taskStatusLabel } from '@features/tasks/utils/status';
import type { TaskRecord } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';
import { IdempotencyKeyManager, semanticMutationValue } from '@/shared/api/idempotency';

interface TaskHeaderBarProps {
  task: TaskRecord;
  showPause?: boolean;
  showResume?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  taskSidebarCollapsed?: boolean;
  metadataSidebarOpen?: boolean;
  onToggleTaskSidebar?: () => void;
  onToggleMetadataSidebar?: () => void;
  onBackToList?: () => void;
  canRename?: boolean;
  mutationDisabledReason?: string | null;
  actions?: ReactNode;
}

export default function TaskHeaderBar({
  task,
  showPause = false,
  showResume = false,
  onPause,
  onResume,
  taskSidebarCollapsed = false,
  metadataSidebarOpen = true,
  onToggleTaskSidebar,
  onToggleMetadataSidebar,
  onBackToList,
  canRename = true,
  mutationDisabledReason = null,
  actions,
}: TaskHeaderBarProps) {
  const t = useT();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(task.title);
  const inputRef = useRef<HTMLInputElement>(null);
  const renameKeyManager = useRef(new IdempotencyKeyManager('task.rename')).current;

  const renameMutation = useMutation({
    mutationFn: async (title: string) => {
      const key = renameKeyManager.keyFor(semanticMutationValue({ taskId: task.task_id, title }));
      return { result: await updateTask(task.task_id, { title }, key), key };
    },
    onSuccess: ({ key }) => {
      renameKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.task_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });

  const startEdit = useCallback(() => {
    if (!canRename) return;
    setEditTitle(task.title);
    setIsEditing(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [canRename, task.title]);

  const commitTitle = useCallback(() => {
    setIsEditing(false);
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== task.title) {
      renameMutation.mutate(trimmed);
    }
  }, [editTitle, task.title, renameMutation]);

  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--osci-color-border)] bg-[var(--osci-topbar-background-translucent)] backdrop-blur-lg px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        {onBackToList ? (
          <button
            type="button"
            onClick={onBackToList}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--osci-color-text-secondary)] transition hover:bg-[var(--osci-color-primary-soft)] hover:text-[var(--osci-color-text)]"
            title={t('pages.tasks.backToList')}
            aria-label={t('pages.tasks.backToList')}
          >
            <ArrowLeft size={16} />
          </button>
        ) : null}
        {onToggleTaskSidebar && (
          <button
            type="button"
            onClick={onToggleTaskSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--osci-color-text-secondary)] transition hover:bg-[var(--osci-color-primary-soft)] hover:text-[var(--osci-color-text)]"
            title={taskSidebarCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
            aria-label={taskSidebarCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
          >
            {taskSidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        )}

        {isEditing ? (
          <input
            ref={inputRef}
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitTitle();
              if (e.key === 'Escape') setIsEditing(false);
            }}
            className="min-w-0 max-w-md rounded-lg border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-2 py-1 text-sm font-semibold text-[var(--osci-color-text)] outline-none focus:border-[var(--osci-color-primary)] focus:ring-2 focus:ring-[var(--osci-color-focus)]"
          />
        ) : (
          <h1
            className={`min-w-0 max-w-md truncate text-sm font-semibold text-[var(--osci-color-text)] transition ${canRename ? 'cursor-pointer hover:bg-[var(--osci-color-surface-subtle)]' : ''}`}
            title={mutationDisabledReason ?? task.title}
            onClick={canRename ? startEdit : undefined}
            tabIndex={canRename ? 0 : undefined}
            onKeyDown={canRename ? (e) => { if (e.key === 'Enter') startEdit(); } : undefined}
          >
            {task.title}
          </h1>
        )}
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${taskStatusClassName(task.status)}`}>
          {taskStatusLabel(t, task.status)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {actions}
        {showPause && onPause && (
          <button
            type="button"
            onClick={onPause}
            className="rounded-lg bg-[var(--osci-color-surface-subtle)] px-3 py-1 text-xs font-medium text-[var(--osci-color-text-secondary)] transition hover:bg-[var(--osci-color-primary-soft)] hover:text-[var(--osci-color-text)]"
          >
            {t('pages.tasks.actions.pause')}
          </button>
        )}
        {showResume && onResume && (
          <button
            type="button"
            onClick={onResume}
            className="rounded-lg bg-[var(--osci-color-primary-soft)] px-3 py-1 text-xs font-medium text-[var(--osci-color-primary)] transition hover:opacity-80"
          >
            {t('pages.tasks.actions.resume')}
          </button>
        )}

        {onToggleMetadataSidebar && (
          <button
            type="button"
            onClick={onToggleMetadataSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--osci-color-text-secondary)] transition hover:bg-[var(--osci-color-primary-soft)] hover:text-[var(--osci-color-text)]"
            title={metadataSidebarOpen ? t('pages.tasks.layout.collapseSidebar') : t('pages.tasks.layout.expandSidebar')}
            aria-label={metadataSidebarOpen ? t('pages.tasks.layout.collapseSidebar') : t('pages.tasks.layout.expandSidebar')}
          >
            {metadataSidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
        )}
      </div>
    </header>
  );
}
