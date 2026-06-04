import { useT } from '../../i18n';
import type { ProjectRecord, TaskSummary } from '../../types';

interface Props {
  projectId: string | null;
  onProjectChange: (id: string | null) => void;
  fromDate: string;
  toDate: string;
  onFromDateChange: (d: string) => void;
  onToDateChange: (d: string) => void;
  tasks: TaskSummary[];
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
  tasks,
  projects,
}: Props) {
  const t = useT();

  return (
    <div className="flex w-full flex-wrap items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3 text-sm">
      <select
        value={projectId ?? ''}
        onChange={(e) => onProjectChange(e.target.value || null)}
        className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm text-[var(--text)]"
        aria-label={t('pages.sessions.timeline.projectFilter')}
      >
        <option value="">{t('pages.sessions.timeline.allProjects')}</option>
        {projects.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.name}
          </option>
        ))}
      </select>

      <span className="text-[var(--border)]">|</span>

      <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        {t('pages.sessions.timeline.from')}
        <input
          type="date"
          value={fromDate}
          onChange={(e) => onFromDateChange(e.target.value)}
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-1 py-0.5 text-xs text-[var(--text)]"
        />
      </label>
      <label className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
        {t('pages.sessions.timeline.to')}
        <input
          type="date"
          value={toDate}
          onChange={(e) => onToDateChange(e.target.value)}
          className="rounded border border-[var(--border)] bg-[var(--surface)] px-1 py-0.5 text-xs text-[var(--text)]"
        />
      </label>

      <span className="text-[var(--border)]">|</span>

      <button
        type="button"
        onClick={() => {
          onFromDateChange(todayStr());
          onToDateChange(todayStr());
        }}
        className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.sessions.timeline.today')}
      </button>
      <button
        type="button"
        onClick={() => {
          onFromDateChange(daysAgoStr(7));
          onToDateChange(todayStr());
        }}
        className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.sessions.timeline.past7Days')}
      </button>
      <button
        type="button"
        onClick={() => {
          onFromDateChange(daysAgoStr(30));
          onToDateChange(todayStr());
        }}
        className="rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs text-[var(--text)] hover:bg-[var(--bg-secondary)]"
      >
        {t('pages.sessions.timeline.past30Days')}
      </button>

      <span className="flex-1" />

      <span className="text-xs text-[var(--text-secondary)]">
        {t('pages.sessions.timeline.taskCount', { count: tasks.length })}
      </span>
    </div>
  );
}
