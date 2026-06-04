import type { TaskSummary } from '../../types';

interface Props {
  task: TaskSummary;
  minTime: number;
  span: number;
}

const STATUS_BAR_CLASSES: Record<string, string> = {
  queued: 'bg-[var(--text-tertiary)]',
  starting: 'bg-[var(--warning)]',
  running: 'bg-[var(--info)]',
  paused: 'bg-[var(--warning)]',
  succeeded: 'bg-[var(--success)]',
  failed: 'bg-[var(--danger)]',
  cancelled: 'bg-[var(--text-tertiary)]',
};

function taskStart(task: TaskSummary): number {
  return new Date(task.started_at ?? task.created_at).getTime();
}

function taskEnd(task: TaskSummary): number {
  return new Date(task.completed_at ?? task.updated_at ?? task.started_at ?? task.created_at).getTime();
}

export function GanttRow({ task, minTime, span }: Props) {
  const startMs = taskStart(task);
  const endMs = Math.max(taskEnd(task), startMs + 1);
  const leftPct = ((startMs - minTime) / span) * 100;
  const widthPct = Math.max(1, ((endMs - startMs) / span) * 100);
  const engine = task.harness_engine ?? task.task_profile ?? 'agent';

  return (
    <div className="flex border-b border-[var(--border)] hover:bg-[var(--bg)]">
      <div className="w-[280px] min-w-[280px] border-r border-[var(--border)] p-2 text-xs">
        <span className="block truncate font-medium text-[var(--text)]" title={task.title}>{task.title}</span>
        <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-[var(--text-secondary)]">
          <span>{task.status}</span>
          <span>{engine}</span>
          <span>{task.latest_output_seq ?? 0} events</span>
        </div>
      </div>
      <div className="relative h-9 flex-1">
        <button
          type="button"
          data-testid="task-timeline-bar"
          className={`absolute top-2 h-5 rounded-full ${STATUS_BAR_CLASSES[task.status] ?? STATUS_BAR_CLASSES.cancelled}`}
          style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
          title={`${task.title} · ${task.status}`}
          aria-label={`Open task run ${task.title}`}
          onClick={() => {
            window.location.href = `/tasks?task=${encodeURIComponent(task.task_id)}`;
          }}
        />
      </div>
    </div>
  );
}
