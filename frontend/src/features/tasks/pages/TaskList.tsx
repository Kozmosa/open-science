import { Search } from 'lucide-react';
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
}: Props) {
  const t = useT();
  const filteredTasks = tasks.filter((task) => matchesTask(task, searchQuery));

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
              <button
                key={task.task_id}
                type="button"
                data-task-id={task.task_id}
                onClick={() => onSelectTask(task.task_id)}
                className={[
                  'group flex w-full flex-col gap-2 rounded-lg border px-3 py-3 text-left transition',
                  isSelected
                    ? 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)] shadow-[var(--osci-shadow-sm)]'
                    : 'border-transparent hover:border-[var(--osci-color-border)] hover:bg-[var(--osci-color-surface-subtle)]',
                ].join(' ')}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0 text-sm font-medium leading-snug text-[var(--osci-color-text)]" title={task.title}>
                    {task.title}
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${taskStatusClassName(task.status)}`}
                    >
                      {taskStatusLabel(t, task.status)}
                    </span>
                  </span>
                </span>
                <span className="truncate text-xs text-[var(--osci-color-text-secondary)]">
                  {task.researcher_type ?? task.task_profile ?? 'researcher'}
                </span>
                <span className="truncate text-[11px] text-[var(--osci-color-text-muted)]">
                  {t('pages.tasks.updatedAt', { time: task.updated_at })}
                </span>
              </button>
            );
          })
        )}
      </div>
    </section>
  );
}
