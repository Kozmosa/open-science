import { Alert } from '@design-system';
import { useLocale, useT } from '@/shared/i18n';
import type { TaskRecord } from '@/shared/types';
import { TechnicalIdentifier } from '@features/tasks/components/TechnicalIdentifier';
import { formatTaskDateTime, taskMetadataLabels } from '@features/tasks/utils/metadataPresentation';

interface TaskMetadataDrawerProps {
  task: TaskRecord;
}

function MetadataRow({
  label,
  value,
  fallback,
}: {
  label: string;
  value: string | number | null;
  fallback: string;
}) {
  return (
    <div className="flex items-start gap-2 border-b border-[var(--osci-color-border)] py-2 last:border-0">
      <span className="w-16 shrink-0 text-xs text-[var(--osci-color-text-secondary)]">{label}</span>
      <span
        className="min-w-0 flex-1 truncate text-right text-xs font-medium text-[var(--osci-color-text)]"
        title={value ? String(value) : fallback}
      >
        {value ?? fallback}
      </span>
    </div>
  );
}

export default function TaskMetadataDrawer({ task }: TaskMetadataDrawerProps) {
  const t = useT();
  const locale = useLocale();
  const labels = taskMetadataLabels[locale];
  const fallback = t('pages.tasks.unavailable');

  const command = task.command?.length
    ? task.command.join(' ')
    : task.runtime?.command?.length
      ? task.runtime.command.join(' ')
      : null;
  const workingDirectory =
    task.working_directory ??
    task.runtime?.working_directory ??
    task.binding?.resolved_workdir ??
    null;
  const workspaceLabel =
    task.workspace_summary?.label ?? task.binding?.workspace?.label ?? null;
  const environmentLabel =
    task.environment_summary?.display_name ??
    task.environment_summary?.alias ??
    task.binding?.environment?.display_name ??
    null;

  return (
    <>
      <div className="mb-3 border-b border-[var(--osci-color-border-subtle)] pb-3">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--osci-color-text-secondary)]">
          {t('pages.tasks.summary')}
        </p>
      </div>

      <div className="flex h-full flex-col gap-5 overflow-y-auto">
        {task.error_summary && (
          <Alert variant="error" className="shrink-0">{task.error_summary}</Alert>
        )}

        <section>
          <h2 className="mb-2 text-sm font-semibold text-[var(--osci-color-text)]">{t('pages.tasks.workspaceEyebrow')}</h2>
          <div className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3">
            <MetadataRow label={t('pages.tasks.metadata.workdir')} value={workingDirectory} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.workspaceLabel')} value={workspaceLabel} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.environmentLabel')} value={environmentLabel} fallback={fallback} />
          </div>
        </section>

        <section>
          <div className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3">
            <MetadataRow label={t('pages.tasks.metadata.command')} value={command} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.metadata.taskInput')} value={task.prompt ?? task.binding?.task_input ?? null} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.created')} value={formatTaskDateTime(task.created_at, locale, fallback)} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.updated')} value={formatTaskDateTime(task.updated_at, locale, fallback)} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.started')} value={formatTaskDateTime(task.started_at, locale, fallback)} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.completed')} value={formatTaskDateTime(task.completed_at, locale, fallback)} fallback={fallback} />
          </div>
        </section>

        <section>
          <h2 className="mb-2 text-sm font-semibold text-[var(--osci-color-text)]">{t('pages.tasks.result')}</h2>
          <div className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3">
            <MetadataRow label={t('pages.tasks.exitCode')} value={task.result?.exit_code ?? task.exit_code ?? null} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.failure')} value={task.result?.failure_category ?? null} fallback={fallback} />
            <MetadataRow label={t('pages.tasks.completed')} value={formatTaskDateTime(task.result?.completed_at ?? task.completed_at, locale, fallback)} fallback={fallback} />
          </div>
        </section>

        <details className="rounded-xl border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3 text-xs">
          <summary className="cursor-pointer py-3 font-semibold text-[var(--osci-color-text)]">{labels.technicalDetails}</summary>
          <dl className="border-t border-[var(--osci-color-border)] py-1">
            <TechnicalIdentifier label={t('pages.tasks.taskId')} value={task.task_id} fallback={fallback} />
          </dl>
        </details>
      </div>
    </>
  );
}
