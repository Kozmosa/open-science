import type { AttemptRecord, SessionRecord } from '../../types';
import { AttemptSegment } from './AttemptSegment';

interface Props {
  session: SessionRecord;
  attempts: AttemptRecord[];
  minTime: number;
  span: number;
}

export function GanttRow({ session, attempts, minTime, span }: Props) {
  return (
    <div className="flex border-b border-[var(--border)] hover:bg-[var(--bg)]">
      <div className="w-[260px] min-w-[260px] p-2 border-r border-[var(--border)] text-xs">
        <span className="font-medium">{session.title}</span>
        <div className="text-[var(--text-secondary)] mt-0.5">
          {session.task_count} attempts · ${session.total_cost_usd.toFixed(2)}
        </div>
      </div>
      <div className="flex-1 relative h-7">
        {attempts.map((a) => {
          const startMs = a.started_at ? new Date(a.started_at).getTime() : null;
          const endMs = a.finished_at ? new Date(a.finished_at).getTime() : Date.now();
          if (startMs === null) return null;
          const leftPct = ((startMs - minTime) / span) * 100;
          const widthPct = Math.max(1, ((endMs - startMs) / span) * 100);
          return (
            <AttemptSegment
              key={a.id}
              attempt={a}
              leftPct={leftPct}
              widthPct={widthPct}
              onClick={() => {
                if (a.task_id) window.location.href = `/tasks/${a.task_id}`;
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
