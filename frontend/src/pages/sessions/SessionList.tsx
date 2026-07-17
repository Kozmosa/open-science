import { useState } from 'react';
import { Input, StatusDot } from '@design-system';
import { useT } from '@/shared/i18n';
import { taskStatusLabel } from '@features/tasks/utils/status';
import type { TaskSummary } from '@/shared/types';

interface Props {
  tasks: TaskSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
}

const STATUS_COLOR: Record<string, 'success' | 'warning' | 'error' | 'idle'> = {
  queued: 'idle',
  starting: 'warning',
  running: 'warning',
  paused: 'warning',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'idle',
};
export function SessionList({ tasks, selectedId, onSelect, loading }: Props) {
  const t = useT();
  const [search, setSearch] = useState('');

  const filtered = tasks.filter((task) =>
    task.title.toLowerCase().includes(search.toLowerCase()) ||
    task.prompt.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex flex-col gap-3 p-2 min-h-0">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t('pages.sessions.sidebarTitle')}</h3>
        <span className="text-xs text-[var(--text-secondary)]">
          {t('pages.sessions.sidebarCount', { count: tasks.length })}
        </span>
      </div>
      <Input
        placeholder={t('pages.sessions.searchPlaceholder')}
        value={search}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
      />
      {loading && filtered.length === 0 ? (
        <p className="px-1 text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
      ) : filtered.length === 0 ? (
        <p className="px-1 text-sm text-[var(--text-tertiary)]">{t('pages.sessions.empty')}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {filtered.map((task) => (
            <li key={task.task_id}>
              <button
                type="button"
                onClick={() => onSelect(task.task_id)}
                className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  selectedId === task.task_id
                    ? 'border border-[var(--info-border)] bg-[var(--info-soft)]'
                    : 'border border-transparent hover:bg-[var(--bg-secondary)]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <StatusDot status={STATUS_COLOR[task.status] ?? 'idle'} />
                  <span className="truncate font-medium text-[var(--text)]" title={task.title}>{task.title}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-secondary)]">
                  <span>{taskStatusLabel(t, task.status)}</span>
                  <span>{task.harness_engine ?? task.task_profile ?? 'agent'}</span>
                  <span>{t('pages.sessions.outputCount', { count: task.latest_output_seq ?? 0 })}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
