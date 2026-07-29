import { useMemo } from 'react';
import type { TaskSummary } from '@/shared/types';
import { useT } from '@/shared/i18n';
import { GanttRow } from './GanttRow';

interface Props {
  tasks: TaskSummary[];
  loading: boolean;
}

function getTaskStart(task: TaskSummary): number {
  return new Date(task.started_at ?? task.created_at).getTime();
}

function getTaskEnd(task: TaskSummary): number {
  return new Date(task.completed_at ?? task.updated_at ?? task.started_at ?? task.created_at).getTime();
}

function getTimeLabel(span: number): string {
  if (span <= 86400000) return 'hour';
  if (span <= 604800000) return 'day';
  return 'week';
}

function generateTimeLabels(
  minTime: number,
  maxTime: number,
  unit: string,
): { label: string; leftPct: number }[] {
  const labels: { label: string; leftPct: number }[] = [];
  const span = maxTime - minTime || 1;
  if (unit === 'hour') {
    const step = 3600000;
    let cur = Math.floor(minTime / step) * step;
    while (cur <= maxTime) {
      labels.push({
        label: new Date(cur).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        leftPct: ((cur - minTime) / span) * 100,
      });
      cur += step;
    }
  } else if (unit === 'day') {
    const step = 86400000;
    const cur = new Date(minTime);
    cur.setHours(0, 0, 0, 0);
    while (cur.getTime() <= maxTime) {
      labels.push({
        label: cur.toLocaleDateString([], { month: 'short', day: 'numeric' }),
        leftPct: ((cur.getTime() - minTime) / span) * 100,
      });
      cur.setTime(cur.getTime() + step);
    }
  } else {
    const step = 604800000;
    const cur = new Date(minTime);
    cur.setHours(0, 0, 0, 0);
    while (cur.getTime() <= maxTime) {
      labels.push({
        label: `W${Math.ceil(cur.getDate() / 7)} ${cur.toLocaleDateString([], { month: 'short' })}`,
        leftPct: ((cur.getTime() - minTime) / span) * 100,
      });
      cur.setTime(cur.getTime() + step);
    }
  }
  return labels;
}

export function GanttChart({ tasks, loading }: Props) {
  const t = useT();
  const { minTime, span, timeLabels } = useMemo(() => {
    if (tasks.length === 0) {
      // Empty-state placeholder range; no real timestamps are rendered.
      const now = 0;
      return {
        minTime: now - 3600000,
        span: 7200000,
        timeLabels: [] as { label: string; leftPct: number }[],
      };
    }

    const min = Math.min(...tasks.map(getTaskStart));
    const max = Math.max(...tasks.map((task) => Math.max(getTaskEnd(task), getTaskStart(task) + 1)));
    const s = max - min || 1;
    return {
      minTime: min,
      span: s,
      timeLabels: generateTimeLabels(min, max, getTimeLabel(s)),
    };
  }, [tasks]);

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--text-tertiary)]">
        {t('pages.sessions.timeline.loading')}
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--text-tertiary)]">
        {t('pages.sessions.timeline.empty')}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 w-full flex-col overflow-x-auto overflow-y-auto rounded-lg border border-[var(--border)]">
      <div className="flex border-b border-[var(--border)] bg-[var(--bg)]">
        <div className="w-[280px] min-w-[280px] border-r-2 border-[var(--border)] p-2 text-xs font-semibold text-[var(--text-secondary)]">
          {t('pages.sessions.timeline.title')}
        </div>
        <div className="relative h-8 flex-1">
          {timeLabels.map((tl) => (
            <div
              key={`${tl.label}-${tl.leftPct}`}
              className="absolute top-0 whitespace-nowrap text-[9px] text-[var(--text-tertiary)]"
              style={{ left: `${tl.leftPct}%`, transform: tl.leftPct > 0 ? 'translateX(-50%)' : 'none' }}
            >
              {tl.label}
            </div>
          ))}
        </div>
      </div>
      {tasks.map((task) => (
        <GanttRow
          key={task.task_id}
          task={task}
          minTime={minTime}
          span={span}
        />
      ))}
    </div>
  );
}
