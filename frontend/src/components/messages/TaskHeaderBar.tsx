import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { updateTask } from '@/shared/api';
import { useT } from '@/shared/i18n';
import { statusClassName } from '@features/tasks/utils/status';
import type { TaskRecord } from '@/shared/types';

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
}: TaskHeaderBarProps) {
  const t = useT();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(task.title);
  const inputRef = useRef<HTMLInputElement>(null);

  const renameMutation = useMutation({
    mutationFn: (title: string) => updateTask(task.task_id, { title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['task', task.task_id] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
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
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg)] px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        {onToggleTaskSidebar && (
          <button
            type="button"
            onClick={onToggleTaskSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)]"
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
            className="min-w-0 max-w-md rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm font-semibold text-[var(--text)] outline-none focus:border-[var(--apple-blue)]"
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
        {showPause && onPause && (
          <button
            type="button"
            onClick={onPause}
            className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
          >
            {t('pages.tasks.actions.pause')}
          </button>
        )}
        {showResume && onResume && (
          <button
            type="button"
            onClick={onResume}
            className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
          >
            {t('pages.tasks.actions.resume')}
          </button>
        )}

        {onToggleMetadataSidebar && (
          <button
            type="button"
            onClick={onToggleMetadataSidebar}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)]"
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
