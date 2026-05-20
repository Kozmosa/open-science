import { useT } from '../../i18n';
import type { SessionRecord, ProjectRecord } from '../../types';

interface Props {
  projectId: string | null;
  onProjectChange: (id: string | null) => void;
  fromDate: string;
  toDate: string;
  onFromDateChange: (d: string) => void;
  onToDateChange: (d: string) => void;
  sessions: SessionRecord[];
  projects: ProjectRecord[];
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoStr(n: number): string {
  const d = new Date(Date.now() - n * 86400000);
  return d.toISOString().slice(0, 10);
}

export function TimelineControls({
  projectId,
  onProjectChange,
  fromDate,
  toDate,
  onFromDateChange,
  onToDateChange,
  sessions,
  projects,
}: Props) {
  const t = useT();

  const totalCost = sessions.reduce((sum, s) => sum + s.total_cost_usd, 0);

  return (
    <div className="flex w-full flex-wrap items-center gap-3 p-3 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm">
      <select
        value={projectId ?? ''}
        onChange={(e) => onProjectChange(e.target.value || null)}
        className="px-2 py-1 border border-[var(--border)] rounded text-sm"
      >
        <option value="">{t('pages.timeline.allProjects')}</option>
        {projects.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.name}
          </option>
        ))}
      </select>

      <span className="text-[var(--border)]">|</span>

      <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        {t('pages.timeline.from')}
        <input
          type="date"
          value={fromDate}
          onChange={(e) => onFromDateChange(e.target.value)}
          className="px-1 py-0.5 border border-[var(--border)] rounded text-xs"
        />
      </label>
      <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        {t('pages.timeline.to')}
        <input
          type="date"
          value={toDate}
          onChange={(e) => onToDateChange(e.target.value)}
          className="px-1 py-0.5 border border-[var(--border)] rounded text-xs"
        />
      </label>

      <span className="text-[var(--border)]">|</span>

      <button
        type="button"
        onClick={() => {
          onFromDateChange(todayStr());
          onToDateChange(todayStr());
        }}
        className="px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.timeline.today')}
      </button>
      <button
        type="button"
        onClick={() => {
          onFromDateChange(daysAgoStr(7));
          onToDateChange(todayStr());
        }}
        className="px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.timeline.past7Days')}
      </button>
      <button
        type="button"
        onClick={() => {
          onFromDateChange(daysAgoStr(30));
          onToDateChange(todayStr());
        }}
        className="px-2 py-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.timeline.past30Days')}
      </button>

      <span className="flex-1" />

      <span className="text-xs text-[var(--text-secondary)]">
        {t('pages.timeline.sessionCount', { count: sessions.length })}
        {totalCost > 0
          ? ` · ${t('pages.timeline.totalCost', { cost: `$${totalCost.toFixed(2)}` })}`
          : ''}
      </span>
    </div>
  );
}
