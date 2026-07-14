import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Skeleton } from '@design-system';
import { getDomainTaskAttempts, getDomainTaskContext } from '@features/domain';
import { queryKeys } from '@/shared/api/queryKeys';
import type { TaskRecord } from '@/shared/types';
import TaskMetadataDrawer from '@/components/messages/TaskMetadataDrawer';

export type TaskDrawerView = 'details' | 'attempts' | 'context' | 'closed';

interface TaskInspectorPanelProps {
  task: TaskRecord;
  view: Exclude<TaskDrawerView, 'closed'>;
  onViewChange: (view: TaskDrawerView) => void;
}

function formatDuration(milliseconds: unknown): string {
  return typeof milliseconds === 'number' ? `${Math.round(milliseconds / 1000)}s` : '—';
}

function AttemptHistory({ taskId }: { taskId: string }) {
  const query = useQuery({
    queryKey: queryKeys.domain.taskAttempts(taskId),
    queryFn: () => getDomainTaskAttempts(taskId),
  });
  if (query.isLoading) return <Skeleton className="h-32 w-full" />;
  if (query.error instanceof Error) return <Alert variant="error">{query.error.message}</Alert>;
  const attempts = query.data?.items ?? [];
  if (attempts.length === 0) {
    return <p className="text-sm text-[var(--osci-color-text-muted)]">No Attempts recorded.</p>;
  }
  return (
    <div className="space-y-3 overflow-y-auto">
      {attempts.map((attempt) => (
        <article key={attempt.attempt_id} className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] p-3">
          <div className="flex items-center justify-between gap-2">
            <strong className="text-sm text-[var(--osci-color-text)]">
              Attempt {attempt.attempt_seq} · {attempt.trigger}
            </strong>
            <span className="text-xs text-[var(--osci-color-text-muted)]">{attempt.status}</span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div><dt className="text-[var(--osci-color-text-muted)]">Started</dt><dd>{attempt.started_at ?? '—'}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">Duration</dt><dd>{formatDuration(attempt.duration_ms)}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">Cost</dt><dd>{attempt.cost_usd == null ? '—' : `$${attempt.cost_usd.toFixed(4)}`}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">Context Version</dt><dd className="truncate" title={attempt.context_version_id ?? undefined}>{attempt.context_version_id ?? '—'}</dd></div>
          </dl>
          <div className="mt-3 text-xs text-[var(--osci-color-text-muted)]">
            Runtime Sessions: {attempt.runtime_sessions.length > 0
              ? attempt.runtime_sessions.map((session) => `${session.engine_name ?? 'runtime'}:${session.status}`).join(', ')
              : 'none'}
          </div>
        </article>
      ))}
    </div>
  );
}

function TaskContextPanel({ taskId }: { taskId: string }) {
  const query = useQuery({
    queryKey: [...queryKeys.tasks.detail(taskId), 'context'],
    queryFn: () => getDomainTaskContext(taskId),
  });
  if (query.isLoading) return <Skeleton className="h-32 w-full" />;
  if (query.error instanceof Error) return <Alert variant="error">{query.error.message}</Alert>;
  const context = query.data;
  if (!context?.context_version_id) {
    return <p className="text-sm text-[var(--osci-color-text-muted)]">No pinned Context Version.</p>;
  }
  return (
    <div className="space-y-3 overflow-y-auto">
      <dl className="rounded-xl border border-[var(--osci-color-border)] p-3 text-xs">
        <div><dt className="text-[var(--osci-color-text-muted)]">Context Version</dt><dd className="break-all">{context.context_version_id}</dd></div>
        <div className="mt-2"><dt className="text-[var(--osci-color-text-muted)]">Snapshot</dt><dd className="break-all">{context.context_snapshot_id ?? 'version fallback'}</dd></div>
        <div className="mt-2"><dt className="text-[var(--osci-color-text-muted)]">Fingerprint</dt><dd className="break-all">{context.fingerprint ?? '—'}</dd></div>
      </dl>
      <pre className="whitespace-pre-wrap rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-muted)] p-3 text-xs text-[var(--osci-color-text)]">{context.content}</pre>
    </div>
  );
}

export default function TaskInspectorPanel({ task, view, onViewChange }: TaskInspectorPanelProps) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid grid-cols-3 gap-1 border-b border-[var(--osci-color-border)] pb-3">
        {(['details', 'attempts', 'context'] as const).map((item) => (
          <Button
            key={item}
            size="sm"
            variant={view === item ? 'primary' : 'ghost'}
            onClick={() => onViewChange(item)}
          >
            {item[0].toUpperCase() + item.slice(1)}
          </Button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {view === 'details' ? <TaskMetadataDrawer task={task} /> : null}
        {view === 'attempts' ? <AttemptHistory taskId={task.task_id} /> : null}
        {view === 'context' ? <TaskContextPanel taskId={task.task_id} /> : null}
      </div>
    </div>
  );
}
