import { useT } from '../../i18n';
import type { TaskOutputEvent, TaskRecord, TaskStatus } from '../../types';

const statusClassName: Record<TaskStatus, string> = {
  queued: 'border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]',
  starting: 'border-blue-500/20 bg-blue-500/10 text-blue-600',
  running: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
  succeeded: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-600',
  failed: 'border-red-500/20 bg-red-500/10 text-red-600',
};

interface TaskDetailProps {
  selectedTask: TaskRecord | null;
  detailError: string | null;
  outputItems: TaskOutputEvent[];
  outputError: string | null;
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
    <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] py-2 last:border-0">
      <span className="text-xs text-[var(--muted-foreground)]">{label}</span>
      <span className="max-w-[70%] text-right text-xs font-medium text-[var(--foreground)]">
        {value ?? fallback}
      </span>
    </div>
  );
}

export default function TaskDetail({
  selectedTask,
  detailError,
  outputItems,
  outputError,
}: TaskDetailProps) {
  const t = useT();
  const metadataFallback = t('pages.tasks.unavailable');

  if (detailError) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--card)] p-6">
        <p className="text-sm text-[var(--destructive)]">{detailError}</p>
      </section>
    );
  }

  if (!selectedTask) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)] p-6">
        <div className="max-w-sm text-center">
          <h2 className="text-base font-semibold text-[var(--foreground)]">
            {t('pages.tasks.noTaskSelected')}
          </h2>
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">
            {t('pages.tasks.noTaskSelectedDescription')}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-[var(--shadow-pane)]">
      <header className="border-b border-[var(--border)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
              {t('pages.tasks.workspaceEyebrow')}
            </p>
            <h1 className="mt-1 truncate text-xl font-semibold tracking-tight text-[var(--foreground)]">
              {selectedTask.title}
            </h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {selectedTask.workspace_summary.label} · {selectedTask.environment_summary.alias} ·{' '}
              {selectedTask.environment_summary.display_name}
            </p>
          </div>
          <span
            className={`rounded-full border px-3 py-1 text-xs font-medium ${statusClassName[selectedTask.status]}`}
          >
            {t(`pages.tasks.status.${selectedTask.status}`)}
          </span>
        </div>
        {selectedTask.error_summary ? (
          <p className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-600">
            {selectedTask.error_summary}
          </p>
        ) : null}
      </header>

      <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[minmax(0,1fr)_320px]">
        <main className="min-h-0 overflow-auto p-5">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[var(--foreground)]">
                {t('pages.tasks.outputTimeline')}
              </h2>
              <span className="text-xs text-[var(--muted-foreground)]">
                {t('pages.tasks.latestSeq', { seq: selectedTask.latest_output_seq })}
              </span>
            </div>
            {outputError ? <p className="text-sm text-[var(--destructive)]">{outputError}</p> : null}
            <div className="min-h-[24rem] space-y-3 rounded-xl border border-[var(--border)] bg-[#0b1020] p-4 text-xs text-gray-100">
              {outputItems.length === 0 ? (
                <p className="text-gray-400">{t('pages.tasks.noOutput')}</p>
              ) : (
                outputItems.map((item) => (
                  <article key={item.seq} className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
                    <p className="mb-2 text-[11px] uppercase tracking-[0.08em] text-gray-400">
                      #{item.seq} · {item.kind} · {item.created_at}
                    </p>
                    <pre className="whitespace-pre-wrap break-words leading-relaxed">{item.content}</pre>
                  </article>
                ))
              )}
            </div>
          </section>

          <section className="mt-5 space-y-3">
            <h2 className="text-sm font-semibold text-[var(--foreground)]">
              {t('pages.tasks.promptLayers')}
            </h2>
            {selectedTask.prompt ? (
              <div className="space-y-3">
                {selectedTask.prompt.layers.map((layer) => (
                  <details
                    key={layer.name}
                    className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4"
                  >
                    <summary className="cursor-pointer text-sm font-medium text-[var(--foreground)]">
                      {layer.label}{' '}
                      <span className="text-xs text-[var(--muted-foreground)]">
                        ({layer.char_count} {t('pages.tasks.chars')})
                      </span>
                    </summary>
                    <pre className="mt-3 overflow-x-auto rounded-lg bg-[var(--code-background)] p-3 text-xs text-[var(--code-foreground)]">
                      {layer.content}
                    </pre>
                  </details>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--muted-foreground)]">
                {t('pages.tasks.promptUnavailable')}
              </p>
            )}
          </section>
        </main>

        <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--background)] p-5 lg:border-l lg:border-t-0">
          <div className="space-y-5">
            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--foreground)]">
                {t('pages.tasks.summary')}
              </h2>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3">
                <MetadataRow label={t('pages.tasks.taskId')} value={selectedTask.task_id} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.created')} value={selectedTask.created_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.updated')} value={selectedTask.updated_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.started')} value={selectedTask.started_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.completed_at} fallback={metadataFallback} />
              </div>
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--foreground)]">
                {t('pages.tasks.binding')}
              </h2>
              {selectedTask.binding ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3">
                  <MetadataRow label={t('pages.tasks.profile')} value={selectedTask.binding.task_profile} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.workdir')} value={selectedTask.binding.resolved_workdir} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.snapshot')} value={selectedTask.binding.snapshot_path} fallback={metadataFallback} />
                </div>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t('pages.tasks.bindingUnavailable')}
                </p>
              )}
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--foreground)]">
                {t('pages.tasks.runtime')}
              </h2>
              {selectedTask.runtime ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3">
                  <MetadataRow label={t('pages.tasks.runner')} value={selectedTask.runtime.runner_kind} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.directory')} value={selectedTask.runtime.working_directory} fallback={metadataFallback} />
                  <MetadataRow
                    label={t('pages.tasks.command')}
                    value={selectedTask.runtime.command.join(' ') || t('pages.tasks.pendingValue')}
                    fallback={metadataFallback}
                  />
                </div>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t('pages.tasks.runtimeUnavailable')}
                </p>
              )}
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--foreground)]">
                {t('pages.tasks.result')}
              </h2>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3">
                <MetadataRow label={t('pages.tasks.exitCode')} value={selectedTask.result.exit_code} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.failure')} value={selectedTask.result.failure_category} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.result.completed_at} fallback={metadataFallback} />
              </div>
            </section>
          </div>
        </aside>
      </div>
    </section>
  );
}
