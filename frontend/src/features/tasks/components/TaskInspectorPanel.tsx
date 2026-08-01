import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Skeleton } from '@design-system';
import { getDomainTaskContext } from '@features/domain';
import { getTaskTurns } from '../api';
import { queryKeys } from '@/shared/api/queryKeys';
import type { TaskRecord } from '@/shared/types';
import TaskMetadataDrawer from './messages/TaskMetadataDrawer';
import { useLocale } from '@/shared/i18n';
import { TechnicalIdentifier } from './TechnicalIdentifier';
import { formatTaskDateTime, taskMetadataLabels } from '../utils/metadataPresentation';

export type TaskDrawerView = 'details' | 'turns' | 'context' | 'closed';

interface TaskInspectorPanelProps {
  task: TaskRecord;
  view: Exclude<TaskDrawerView, 'closed'>;
  onViewChange: (view: TaskDrawerView) => void;
}

function formatDuration(milliseconds: unknown): string {
  return typeof milliseconds === 'number' ? `${Math.round(milliseconds / 1000)}s` : '—';
}

function TurnHistory({ taskId }: { taskId: string }) {
  const locale = useLocale();
  const labels = taskMetadataLabels[locale];
  const query = useQuery({
    queryKey: queryKeys.tasks.turns(taskId),
    queryFn: () => getTaskTurns(taskId),
  });
  if (query.isLoading) return <Skeleton className="h-32 w-full" />;
  if (query.error instanceof Error) return <Alert variant="error">{query.error.message}</Alert>;
  const turns = query.data?.items ?? [];
  if (turns.length === 0) {
    return <p className="text-sm text-[var(--osci-color-text-muted)]">{labels.attemptsEmpty}</p>;
  }
  return (
    <div className="space-y-3 overflow-y-auto">
      {turns.map((turn) => {
        const startedAt = typeof turn.started_at === 'string' ? turn.started_at : null;
        const finishedAt = typeof turn.finished_at === 'string' ? turn.finished_at : null;
        const duration = startedAt && finishedAt
          ? Math.max(0, new Date(finishedAt).getTime() - new Date(startedAt).getTime())
          : null;
        return <article key={turn.turn_id} className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] p-3">
          <div className="flex items-center justify-between gap-2">
            <strong className="text-sm text-[var(--osci-color-text)]">
              Turn {turn.turn_seq}
            </strong>
            <span className="text-xs text-[var(--osci-color-text-muted)]">{turn.status}</span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div><dt className="text-[var(--osci-color-text-muted)]">{labels.started}</dt><dd>{formatTaskDateTime(startedAt, locale)}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">{labels.finished}</dt><dd>{formatTaskDateTime(finishedAt, locale)}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">{labels.duration}</dt><dd>{formatDuration(duration)}</dd></div>
            <div><dt className="text-[var(--osci-color-text-muted)]">{labels.cost}</dt><dd>—</dd></div>
          </dl>
          <details className="mt-3 border-t border-[var(--osci-color-border)] text-xs">
            <summary className="cursor-pointer py-2 font-medium text-[var(--osci-color-text)]">{labels.technicalDetails}</summary>
            <dl>
              <TechnicalIdentifier label="Turn ID" value={turn.turn_id} />
              <TechnicalIdentifier label={labels.contextSnapshot} value={typeof turn.context_snapshot_ref === 'string' ? turn.context_snapshot_ref : null} />
            </dl>
          </details>
        </article>
      })}
    </div>
  );
}

function TaskContextPanel({ taskId }: { taskId: string }) {
  const locale = useLocale();
  const labels = taskMetadataLabels[locale];
  const query = useQuery({
    queryKey: [...queryKeys.tasks.detail(taskId), 'context'],
    queryFn: () => getDomainTaskContext(taskId),
  });
  if (query.isLoading) return <Skeleton className="h-32 w-full" />;
  if (query.error instanceof Error) return <Alert variant="error">{query.error.message}</Alert>;
  const context = query.data;
  if (!context?.context_version_id) {
    return <p className="text-sm text-[var(--osci-color-text-muted)]">{labels.contextEmpty}</p>;
  }
  return (
    <div className="space-y-3 overflow-y-auto">
      <h3 className="text-sm font-semibold text-[var(--osci-color-text)]">{labels.pinnedContext}</h3>
      <pre className="whitespace-pre-wrap rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] p-3 text-xs text-[var(--osci-color-text)]">{context.content}</pre>
      <details className="rounded-xl border border-[var(--osci-color-border)] px-3 text-xs">
        <summary className="cursor-pointer py-3 font-medium text-[var(--osci-color-text)]">{labels.technicalDetails}</summary>
        <dl className="border-t border-[var(--osci-color-border)] py-1">
          <TechnicalIdentifier label={labels.contextVersion} value={context.context_version_id} />
          <TechnicalIdentifier label={labels.contextSnapshot} value={context.context_snapshot_id} fallback="version fallback" />
          <TechnicalIdentifier label={labels.fingerprint} value={context.fingerprint} />
        </dl>
      </details>
    </div>
  );
}

export default function TaskInspectorPanel({ task, view, onViewChange }: TaskInspectorPanelProps) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid grid-cols-3 gap-1 border-b border-[var(--osci-color-border)] pb-3">
        {(['details', 'turns', 'context'] as const).map((item) => (
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
        {view === 'turns' ? <TurnHistory taskId={task.task_id} /> : null}
        {view === 'context' ? <TaskContextPanel taskId={task.task_id} /> : null}
      </div>
    </div>
  );
}
