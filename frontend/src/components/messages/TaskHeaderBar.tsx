import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { updateTask } from '@/shared/api';
import { useT } from '@/shared/i18n';
import { statusClassName } from '@features/tasks/utils/status';
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
    setEditTitle(task.title);
    setIsEditing(true);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [task.title]);

  const commitTitle = useCallback(() => {
    setIsEditing(false);
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== task.title) {
      renameMutation.mutate(trimmed);
    }
  }, [editTitle, task.title, renameMutation]);

  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--prism-glass)]/90 backdrop-blur-lg px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        {onToggleTaskSidebar && (
          <button
            type="button"
            onClick={onToggleTaskSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition hover:bg-[var(--prism-primary-soft)] hover:text-[var(--foreground)]"
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
            className="min-w-0 max-w-md rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm font-semibold text-[var(--text)] outline-none focus:border-[var(--prism-primary)] focus:ring-2 focus:ring-[var(--ring)]"
          />
        ) : (
          <h1
            className="min-w-0 max-w-md cursor-pointer truncate text-sm font-semibold text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
            title={task.title}
            onClick={startEdit}
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') startEdit(); }}
          >
            {task.title}
          </h1>
        )}
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusClassName[task.status]}`}>
          {t(`pages.tasks.status.${task.status}`)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {actions}
        {showPause && onPause && (
          <button
            type="button"
            onClick={onPause}
            className="rounded-lg bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--prism-primary-soft)] hover:text-[var(--foreground)]"
          >
            {t('pages.tasks.actions.pause')}
          </button>
        )}
        {showResume && onResume && (
          <button
            type="button"
            onClick={onResume}
            className="rounded-lg bg-[var(--prism-primary-soft)] px-3 py-1 text-xs font-medium text-[var(--prism-primary)] transition hover:bg-[var(--prism-primary-soft)]/70"
          >
            {t('pages.tasks.actions.resume')}
          </button>
        )}

        {onToggleMetadataSidebar && (
          <button
            type="button"
            onClick={onToggleMetadataSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition hover:bg-[var(--prism-primary-soft)] hover:text-[var(--foreground)]"
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
