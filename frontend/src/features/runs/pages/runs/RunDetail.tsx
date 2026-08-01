import { SectionStack, semanticToneClasses } from '@design-system';
import { useLocale, useT } from '@/shared/i18n';
import { formatTaskDateTime, taskStatusLabel } from '@features/tasks';
import type { TaskRecord } from '@/shared/types';
import type { ProjectUsageSummaryResponse, TurnResponse } from '@/shared/api/transportTypes';
import { TurnChain } from './TurnChain';

interface Props {
  detail: TaskRecord | null;
  turns: TurnResponse[];
  usage: ProjectUsageSummaryResponse | null;
  loading: boolean;
  selectedId: string | null;
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  queued: semanticToneClasses.muted,
  starting: semanticToneClasses.warning,
  running: semanticToneClasses.info,
  paused: semanticToneClasses.warning,
  succeeded: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  cancelled: semanticToneClasses.muted,
};

function DetailRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  const text = value == null || value === '' ? '—' : String(value);
  return (
    <div className="flex items-start gap-3 border-b border-[var(--border)] py-2 last:border-0">
      <span className="w-32 shrink-0 text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">{label}</span>
      <span className="min-w-0 flex-1 break-words text-sm text-[var(--text)]" title={text}>{text}</span>
    </div>
  );
}

export function RunDetail({ detail, turns, usage, loading, selectedId }: Props) {
  const t = useT();
  const locale = useLocale();

  if (!selectedId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('pages.runs.selectPrompt')}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('common.loading')}
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('pages.runs.notFound')}
      </div>
    );
  }

  const engine = detail.harness_engine ?? detail.execution_engine ?? detail.task_profile ?? 'agent';
  const workdir = detail.working_directory ?? detail.runtime?.working_directory ?? detail.binding?.resolved_workdir ?? null;
  const command = detail.command?.length ? detail.command.join(' ') : detail.runtime?.command?.join(' ') ?? null;

  return (
    <div className="p-4">
      <SectionStack gap={4}>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="min-w-0 truncate text-lg font-semibold text-[var(--text)]" title={detail.title}>{detail.title}</h2>
          <span
            className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE_CLASSES[detail.status] ?? STATUS_BADGE_CLASSES.cancelled}`}
          >
            {taskStatusLabel(t, detail.status)}
          </span>
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
          <DetailRow label={t('pages.runs.detail.prompt')} value={detail.prompt} />
          <DetailRow label={t('pages.runs.detail.engine')} value={engine} />
          <DetailRow label={t('pages.runs.detail.project')} value={detail.project_id} />
          <DetailRow label={t('pages.runs.detail.workspace')} value={detail.workspace_id} />
          <DetailRow label={t('pages.runs.detail.environment')} value={detail.environment_id} />
          <DetailRow label={t('pages.runs.detail.workdir')} value={workdir} />
          <DetailRow label={t('pages.runs.detail.command')} value={command} />
          <DetailRow label={t('pages.runs.detail.started')} value={formatTaskDateTime(detail.started_at, locale)} />
          <DetailRow label={t('pages.runs.detail.completed')} value={formatTaskDateTime(detail.completed_at, locale)} />
          <DetailRow label={t('pages.runs.detail.outputSeq')} value={detail.latest_output_seq ?? 0} />
          <DetailRow label={t('pages.runs.detail.exitCode')} value={detail.exit_code} />
        </div>

        {detail.error_summary ? (
          <div className={`rounded-lg border px-3 py-2 text-sm ${semanticToneClasses.danger}`}>
            {detail.error_summary}
          </div>
        ) : null}

        {usage ? (
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3">
            <DetailRow label={t('pages.runs.usage.tasks')} value={usage.task_count} />
            <DetailRow label="Turns" value={usage.attempt_count} />
            <DetailRow label={t('pages.runs.usage.tokens')} value={usage.total_tokens} />
            <DetailRow label={t('pages.runs.usage.cost')} value={`$${usage.total_cost_usd.toFixed(2)}`} />
          </div>
        ) : null}

        <TurnChain turns={turns} />
      </SectionStack>
    </div>
  );
}
