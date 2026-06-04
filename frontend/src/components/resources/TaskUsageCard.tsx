import type { TaskTokenUsageSummary } from '../../types';
import { useT } from '../../i18n';

interface Props {
  summary: TaskTokenUsageSummary | null;
  loading: boolean;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

function formatDuration(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return '—';
  const totalMinutes = Math.round(ms / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0 && minutes > 0) return `${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h`;
  return `${minutes}m`;
}

export default function TaskUsageCard({ summary, loading }: Props) {
  const t = useT();

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">{t('pages.resources.taskUsage.title')}</h3>
          <p className="text-xs text-[var(--text-secondary)]">{t('pages.resources.taskUsage.description')}</p>
        </div>
        <span className="text-xs text-[var(--text-tertiary)]">
          {loading ? t('common.loading') : t('pages.resources.taskUsage.taskCount', { count: summary?.task_count ?? 0 })}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
          <p className="text-xs text-[var(--text-secondary)]">{t('pages.resources.taskUsage.totalTokens')}</p>
          <p className="mt-1 text-xl font-semibold text-[var(--text)]">{formatTokens(summary?.total_tokens ?? 0)}</p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
          <p className="text-xs text-[var(--text-secondary)]">{t('pages.resources.taskUsage.totalDuration')}</p>
          <p className="mt-1 text-xl font-semibold text-[var(--text)]">{formatDuration(summary?.total_duration_ms)}</p>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
          <p className="text-xs text-[var(--text-secondary)]">{t('pages.resources.taskUsage.medianDuration')}</p>
          <p className="mt-1 text-xl font-semibold text-[var(--text)]">{formatDuration(summary?.median_duration_ms)}</p>
        </div>
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">{t('pages.resources.taskUsage.topTasks')}</p>
        {summary?.top_tasks.length ? (
          <ol className="space-y-2">
            {summary.top_tasks.map((task) => (
              <li key={task.task_id} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-sm font-medium text-[var(--text)]" title={task.title}>{task.title}</span>
                  <span className="shrink-0 text-xs text-[var(--text-secondary)]">
                    {t('pages.resources.taskUsage.tokens', { count: formatTokens(task.total_tokens) })}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--text-tertiary)]">
                  <span>{task.harness_engine}</span>
                  <span>{formatDuration(task.duration_ms)}</span>
                  <span>${task.cost_usd.toFixed(2)}</span>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-[var(--text-tertiary)]">{t('pages.resources.taskUsage.noTopTasks')}</p>
        )}
      </div>
    </div>
  );
}
