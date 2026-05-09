import { Search } from 'lucide-react';
import { useT } from '../../i18n';
import type { TaskSummary } from '../../types';
import { statusClassName } from './status';

interface Props {
  tasks: TaskSummary[];
  selectedTaskId: string | null;
  tasksError: string | null;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onSelectTask: (taskId: string) => void;
  onArchiveTask: (taskId: string) => void;
  onCancelTask: (taskId: string) => void;
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
  onArchiveTask,
  onCancelTask,
}: Props) {
  const t = useT();
  const filteredTasks = tasks.filter((task) => matchesTask(task, searchQuery));

  const canCancel = (status: string) => status === 'queued' || status === 'starting' || status === 'running';
  const canArchive = (status: string) => status === 'succeeded' || status === 'failed' || status === 'cancelled';

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <label className="relative mb-3 block">
        <span className="sr-only">{t('pages.tasks.searchLabel')}</span>
        <Search
          size={15}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]"
        />
        <input
          aria-label={t('pages.tasks.searchLabel')}
          value={searchQuery}
          onChange={(event) => onSearchQueryChange(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] pl-9 pr-3 text-sm text-[var(--text)] outline-none transition placeholder:text-[var(--text-secondary)] focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder={t('pages.tasks.searchPlaceholder')}
        />
      </label>

      {tasksError ? <p className="mb-3 text-sm text-[#ff3b30]">{tasksError}</p> : null}

      <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
        {tasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-sm text-[var(--text-secondary)]">
            {t('pages.tasks.empty')}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-sm text-[var(--text-secondary)]">
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
                  'group flex w-full flex-col gap-2 rounded-lg border px-3 py-3 text-left transition',
                  isSelected
                    ? 'border-[var(--apple-blue)]/35 bg-[var(--apple-blue)]/10 shadow-sm'
                    : 'border-transparent hover:border-[var(--border)] hover:bg-[var(--bg-secondary)]',
                ].join(' ')}
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="min-w-0 text-sm font-medium leading-snug text-[var(--text)]">
                    {task.title}
                  </span>
                  <span className="flex items-center gap-2">
                    {canCancel(task.status) ? (
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          onCancelTask(task.task_id);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.stopPropagation();
                            onCancelTask(task.task_id);
                          }
                        }}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)] opacity-0 transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)] group-hover:opacity-100"
                      >
                        {t('pages.tasks.actions.cancel')}
                      </span>
                    ) : null}
                    {canArchive(task.status) ? (
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          onArchiveTask(task.task_id);
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.stopPropagation();
                            onArchiveTask(task.task_id);
                          }
                        }}
                        className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)] opacity-0 transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)] group-hover:opacity-100"
                      >
                        {t('pages.tasks.actions.archive')}
                      </span>
                    ) : null}
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusClassName[task.status]}`}
                    >
                      {t(`pages.tasks.status.${task.status}`)}
                    </span>
                  </span>
                </span>
                <span className="truncate text-xs text-[var(--text-secondary)]">
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
