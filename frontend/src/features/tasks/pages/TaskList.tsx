import { RefreshCw, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useT } from '@/shared/i18n';
import type { TaskSummary } from '@/shared/types';
import { taskStatusClassName, taskStatusLabel } from '../utils/status';

interface Props {
  tasks: TaskSummary[];
  selectedTaskId: string | null;
  tasksError: string | null;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onSelectTask: (taskId: string) => void;
  canRenameTask: (task: TaskSummary) => boolean;
  onRenameTask: (taskId: string, title: string) => void;
  renamingTaskId: string | null;
}

function matchesTask(task: TaskSummary, query: string): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  return [
    task.title,
    task.task_id,
    task.status,
    task.researcher_type ?? task.task_profile ?? '',
  ].some((value) => value.toLowerCase().includes(normalizedQuery));
}

export default function TaskList({
  tasks,
  selectedTaskId,
  tasksError,
  searchQuery,
  onSearchQueryChange,
  onSelectTask,
  canRenameTask,
  onRenameTask,
  renamingTaskId,
}: Props) {
  const t = useT();
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);
  const filteredTasks = tasks.filter((task) => matchesTask(task, searchQuery));

  useEffect(() => {
    if (editingTaskId !== null) {
      editInputRef.current?.focus();
      editInputRef.current?.select();
    }
  }, [editingTaskId]);

  const startRename = (task: TaskSummary) => {
    if (!canRenameTask(task)) return;
    setEditingTaskId(task.task_id);
    setEditTitle(task.title);
  };

  const finishRename = (task: TaskSummary) => {
    if (editingTaskId !== task.task_id) return;
    setEditingTaskId(null);
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== task.title) {
      onRenameTask(task.task_id, trimmed);
    }
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <label className="relative mb-3 block">
        <span className="sr-only">{t('pages.tasks.searchLabel')}</span>
        <Search
          size={15}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--osci-color-text-secondary)]"
        />
        <input
          aria-label={t('pages.tasks.searchLabel')}
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
          className="w-full rounded-lg border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] pl-9 pr-3 py-2 text-sm text-[var(--osci-color-text)] outline-none transition placeholder:text-[var(--osci-color-text-muted)] focus:border-[var(--osci-color-primary)] focus:ring-2 focus:ring-[var(--osci-color-focus)]"
          placeholder={t('pages.tasks.searchPlaceholder')}
        />
      </label>

      {tasksError ? <p className="mb-3 text-sm text-[var(--osci-color-danger)]">{tasksError}</p> : null}

      <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
        {tasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] p-4 text-sm text-[var(--osci-color-text-secondary)]">
            {t('pages.tasks.empty')}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] p-4 text-sm text-[var(--osci-color-text-secondary)]">
            {t('pages.tasks.noSearchResults', { query: searchQuery })}
          </div>
        ) : (
          filteredTasks.map((task) => {
            const isSelected = selectedTaskId === task.task_id;
            return (
              <div
                key={task.task_id}
                data-task-id={task.task_id}
                className={[
                  'group flex w-full flex-col gap-2 rounded-lg border px-3 py-3 text-left transition',
                  isSelected
                    ? 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)] shadow-[var(--osci-shadow-sm)]'
                    : 'border-transparent hover:border-[var(--osci-color-border)] hover:bg-[var(--osci-color-surface-subtle)]',
                ].join(' ')}
              >
                <div className="flex items-start justify-between gap-2">
                  {editingTaskId === task.task_id ? (
                    <input
                      ref={editInputRef}
                      aria-label={t('pages.tasks.renameTaskLabel')}
                      value={editTitle}
                      disabled={renamingTaskId === task.task_id}
                      onChange={(event) => setEditTitle(event.target.value)}
                      onBlur={() => finishRename(task)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          finishRename(task);
                        }
                        if (event.key === 'Escape') {
                          event.preventDefault();
                          setEditingTaskId(null);
                        }
                      }}
                      className="min-w-0 flex-1 rounded-md border border-[var(--osci-color-primary)] bg-[var(--osci-color-surface)] px-2 py-1 text-sm font-medium text-[var(--osci-color-text)] outline-none ring-2 ring-[var(--osci-color-focus)]"
                    />
                  ) : (
                    <button
                      type="button"
                      disabled={!canRenameTask(task) || renamingTaskId === task.task_id}
                      onClick={() => startRename(task)}
                      aria-label={t('pages.tasks.renameTaskLabel')}
                      className="min-w-0 flex-1 truncate rounded-sm text-left text-sm font-medium leading-snug text-[var(--osci-color-text)] enabled:cursor-text enabled:hover:underline disabled:cursor-default"
                      title={canRenameTask(task) ? t('pages.tasks.renameTaskHint') : task.title}
                    >
                      {task.title}
                    </button>
                  )}
                  <span className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      aria-label={t('pages.tasks.actions.refreshTaskName')}
                      title={t('pages.tasks.actions.refreshTaskNameTodo')}
                      onClick={() => { /* TODO: Generate and persist a Task title with an LLM. */ }}
                      className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--osci-color-text-muted)] transition hover:bg-[var(--osci-color-surface)] hover:text-[var(--osci-color-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--osci-color-focus)]"
                    >
                      <RefreshCw size={13} />
                    </button>
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${taskStatusClassName(task.status)}`}
                    >
                      {taskStatusLabel(t, task.status)}
                    </span>
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => onSelectTask(task.task_id)}
                  aria-label={task.title}
                  className="flex w-full flex-col gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--osci-color-focus)]"
                >
                  <span className="truncate text-xs text-[var(--osci-color-text-secondary)]">
                    {task.researcher_type ?? task.task_profile ?? 'researcher'}
                  </span>
                  <span className="truncate text-[11px] text-[var(--osci-color-text-muted)]">
                    {t('pages.tasks.updatedAt', { time: task.updated_at })}
                  </span>
                </button>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
