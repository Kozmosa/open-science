import { Search } from 'lucide-react';
import { useT } from '../../i18n';
import type { TaskStatus, TaskSummary } from '../../types';

const statusClassName: Record<TaskStatus, string> = {
  queued: 'border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]',
  starting: 'border-blue-500/20 bg-blue-500/10 text-blue-600',
  running: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
  succeeded: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
  failed: 'border-red-500/20 bg-red-500/10 text-red-600',
};

interface TaskListProps {
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
    task.workspace_summary.label,
    task.environment_summary.alias,
    task.environment_summary.display_name,
  ].some((value) => value.toLowerCase().includes(normalizedQuery));
}

export default function TaskList({
  tasks,
  selectedTaskId,
  tasksError,
  searchQuery,
  onSearchQueryChange,
  onSelectTask,
}: TaskListProps) {
  const t = useT();
  const filteredTasks = tasks.filter((task) => matchesTask(task, searchQuery));

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <label className="relative mb-3 block">
        <span className="sr-only">{t('pages.tasks.searchLabel')}</span>
        <Search
          size={15}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
        />
        <input
          aria-label={t('pages.tasks.searchLabel')}
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
          className="h-9 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] pl-9 pr-3 text-sm text-[var(--foreground)] shadow-[var(--shadow-input)] outline-none transition placeholder:text-[var(--muted-foreground)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
          placeholder={t('pages.tasks.searchPlaceholder')}
        />
      </label>

      {tasksError ? <p className="mb-3 text-sm text-[var(--destructive)]">{tasksError}</p> : null}

      <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
        {tasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--muted)] p-4 text-sm text-[var(--muted-foreground)]">
            {t('pages.tasks.empty')}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--muted)] p-4 text-sm text-[var(--muted-foreground)]">
            {t('pages.tasks.noSearchResults', { query: searchQuery })}
          </div>
        ) : (
          filteredTasks.map((task) => {
            const isSelected = selectedTaskId === task.task_id;
            return (
              <button
                key={task.task_id}
                type="button"
                onClick={() => onSelectTask(task.task_id)}
                className={[
                  'flex w-full flex-col gap-2 rounded-lg border px-3 py-3 text-left transition',
                  isSelected
                    ? 'border-[var(--accent)]/35 bg-[var(--accent)]/10 shadow-[var(--shadow-card)]'
                    : 'border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]',
                ].join(' ')}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0 text-sm font-medium leading-snug text-[var(--foreground)]">
                    {task.title}
                  </span>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusClassName[task.status]}`}
                  >
                    {t(`pages.tasks.status.${task.status}`)}
                  </span>
                </span>
                <span className="truncate text-xs text-[var(--muted-foreground)]">
                  {task.workspace_summary.label} · {task.environment_summary.alias}
                </span>
                <span className="truncate text-[11px] text-[var(--text-tertiary)]">
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
