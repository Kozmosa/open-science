import { useMemo } from 'react';
import type { AttemptRecord, SessionRecord } from '../../types';
import { useT } from '../../i18n';
import { GanttRow } from './GanttRow';

interface Props {
  sessions: SessionRecord[];
  details: Record<string, AttemptRecord[]>;
  loading: boolean;
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
  const span = maxTime - minTime;
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

export function GanttChart({ sessions, details, loading }: Props) {
  const t = useT();
  const { minTime, span, timeLabels, detailMap } = useMemo(() => {
    const allAttempts = Object.values(details).flat();
    const times = allAttempts
      .map((a) => (a.started_at ? new Date(a.started_at).getTime() : null))
      .filter(Boolean) as number[];
    if (times.length === 0) {
      const now = Date.now();
      return {
        minTime: now - 3600000,
        span: 7200000,
        timeLabels: [] as { label: string; leftPct: number }[],
        detailMap: details,
      };
    }

    const min = Math.min(...times);
    const max = Math.max(
      ...allAttempts.map((a) =>
        a.finished_at ? new Date(a.finished_at).getTime() : Date.now(),
      ),
    );
    const s = max - min || 1;
    return {
      minTime: min,
      span: s,
      timeLabels: generateTimeLabels(min, max, getTimeLabel(s)),
      detailMap: details,
    };
  }, [details]);

  if (loading) {
    return <p className="text-sm text-gray-400 p-4">{t('pages.sessions.timeline.loading')}</p>;
  }

  if (sessions.length === 0) {
    return <p className="text-sm text-gray-400 p-4">{t('pages.sessions.timeline.empty')}</p>;
  }

  return (
    <div className="w-full border border-[var(--border)] rounded-lg overflow-x-auto overflow-y-auto">
      <div className="flex bg-[var(--bg)] border-b border-[var(--border)]">
        <div className="w-[260px] min-w-[260px] p-2 border-r-2 border-[var(--border)] text-xs font-semibold text-[var(--text-secondary)]">
          {t('pages.sessions.timeline.title')}
        </div>
        <div className="flex-1 relative h-8">
          {timeLabels.map((tl, i) => (
            <div
              key={i}
              className="absolute top-0 text-[9px] text-gray-400 whitespace-nowrap"
              style={{ left: `${tl.leftPct}%`, transform: i > 0 ? 'translateX(-50%)' : 'none' }}
            >
              {tl.label}
            </div>
          ))}
        </div>
      </div>
      {sessions.map((s) => (
        <GanttRow
          key={s.id}
          session={s}
          attempts={detailMap[s.id] ?? []}
          minTime={minTime}
          span={span}
        />
      ))}
    </div>
  );
}
