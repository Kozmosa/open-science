import type { TaskStatus, TaskSummary } from '../../types';

const statusLabel: Record<TaskStatus, string> = {
  queued: 'Queued',
  starting: 'Starting',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
};

interface TaskListProps {
  tasks: TaskSummary[];
  selectedTaskId: string | null;
  tasksError: string | null;
  onSelectTask: (taskId: string) => void;
}

export default function TaskList({
  tasks,
  selectedTaskId,
  tasksError,
  onSelectTask,
}: TaskListProps) {
  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2
          className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          Task list
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          All harness-managed tasks are listed below.
        </p>
      </div>
      {tasksError ? <p className="text-sm text-[#ff3b30]">{tasksError}</p> : null}
      <div className="space-y-3">
        {tasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
            No tasks have been created yet.
          </div>
        ) : (
          tasks.map((task) => (
            <button
              key={task.task_id}
              type="button"
              onClick={() => onSelectTask(task.task_id)}
              className={[
                'flex w-full flex-col gap-2 rounded-lg px-4 py-4 text-left transition',
                selectedTaskId === task.task_id
                  ? 'bg-[var(--apple-blue)]/10'
                  : 'bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)]',
              ].join(' ')}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm font-semibold text-[var(--text)]">{task.title}</span>
                <span className="rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 py-1 text-xs font-medium text-[var(--text)]">
                  {statusLabel[task.status]}
                </span>
              </div>
              <p className="text-xs tracking-[-0.12px] text-[var(--text-secondary)]">
                {task.workspace_summary.label} · {task.environment_summary.alias}
              </p>
              <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                Updated {task.updated_at}
              </p>
            </button>
          ))
        )}
      </div>
    </section>
  );
}
