import { useState } from 'react';
import { Alert } from '../../components/ui';
import { useT } from '../../i18n';
import type { TaskOutputEvent, TaskRecord } from '../../types';
import { statusClassName } from './status';

interface Props {
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
    <div className="flex items-start gap-4 border-b border-[var(--border)] py-2 last:border-0">
      <span className="w-28 shrink-0 text-xs text-[var(--text-secondary)]">{label}</span>
      <span className="min-w-0 flex-1 truncate text-right text-xs font-medium text-[var(--text)]">
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
}: Props) {
  const t = useT();
  const [layout, setLayout] = useState<'split' | 'main' | 'aside'>('split');
  const metadataFallback = t('pages.tasks.unavailable');

  if (detailError) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        <p className="text-sm text-[#ff3b30]">{detailError}</p>
      </section>
    );
  }

  if (!selectedTask) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="max-w-sm text-center">
          <h2 className="text-base font-semibold text-[var(--text)]">
            {t('pages.tasks.noTaskSelected')}
          </h2>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            {t('pages.tasks.noTaskSelectedDescription')}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
      <header className="border-b border-[var(--border)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              {t('pages.tasks.workspaceEyebrow')}
            </p>
            <h1 className="mt-1 truncate text-xl font-semibold tracking-tight text-[var(--text)]">
              {selectedTask.title}
            </h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
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
          <Alert variant="error" className="mt-3">
            {selectedTask.error_summary}
          </Alert>
        ) : null}
      </header>

      <div
        className={[
          'grid min-h-0 flex-1 gap-0 overflow-hidden transition-all duration-300 ease-in-out',
          layout === 'split' && 'lg:grid-cols-[minmax(0,1fr)_320px]',
          layout === 'main' && 'lg:grid-cols-[1fr_0fr]',
          layout === 'aside' && 'lg:grid-cols-[0fr_1fr]',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {layout !== 'aside' && (
        <main className="min-h-0 overflow-auto p-5">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.outputTimeline')}
              </h2>
              <div className="flex items-center gap-3">
                <span className="text-xs text-[var(--text-secondary)]">
                  {t('pages.tasks.latestSeq', { seq: selectedTask.latest_output_seq })}
                </span>
                <button
                  type="button"
                  onClick={() => setLayout(layout === 'main' ? 'split' : 'main')}
                  className="rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
                  aria-label={layout === 'main' ? 'Collapse panel' : 'Expand panel'}
                >
                  {layout === 'main' ? '<<' : '>>'}
                </button>
              </div>
            </div>
            {outputError ? <p className="text-sm text-[#ff3b30]">{outputError}</p> : null}
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
            <h2 className="text-sm font-semibold text-[var(--text)]">
              {t('pages.tasks.promptLayers')}
            </h2>
            {selectedTask.prompt ? (
              <div className="space-y-3">
                {selectedTask.prompt.layers.map((layer) => (
                  <details
                    key={layer.name}
                    className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4"
                  >
                    <summary className="cursor-pointer text-sm font-medium text-[var(--text)]">
                      {layer.label}{' '}
                      <span className="text-xs text-[var(--text-secondary)]">
                        ({layer.char_count} {t('pages.tasks.chars')})
                      </span>
                    </summary>
                    <pre className="mt-3 overflow-x-auto rounded-lg bg-[var(--bg-tertiary)] p-3 text-xs text-[var(--text)]">
                      {layer.content}
                    </pre>
                  </details>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--text-secondary)]">
                {t('pages.tasks.promptUnavailable')}
              </p>
            )}
          </section>
        </main>
        )}

        {layout !== 'main' && (
        <aside className="min-h-0 overflow-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-l lg:border-t-0">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text)]">
              {t('pages.tasks.summary')}
            </h2>
            <button
              type="button"
              onClick={() => setLayout(layout === 'aside' ? 'split' : 'aside')}
              className="rounded-md bg-[var(--bg-secondary)] px-2 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
              aria-label={layout === 'aside' ? 'Collapse panel' : 'Expand panel'}
            >
              {layout === 'aside' ? '>>' : '<<'}
            </button>
          </div>
          <div className="space-y-5">
            <section>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                <MetadataRow label={t('pages.tasks.taskId')} value={selectedTask.task_id} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.created')} value={selectedTask.created_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.updated')} value={selectedTask.updated_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.started')} value={selectedTask.started_at} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.completed_at} fallback={metadataFallback} />
              </div>
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.binding')}
              </h2>
              {selectedTask.binding ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                  <MetadataRow label={t('pages.tasks.profile')} value={selectedTask.binding.task_profile} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.workdir')} value={selectedTask.binding.resolved_workdir} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.snapshot')} value={selectedTask.binding.snapshot_path} fallback={metadataFallback} />
                </div>
              ) : (
                <p className="text-sm text-[var(--text-secondary)]">
                  {t('pages.tasks.bindingUnavailable')}
                </p>
              )}
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.runtime')}
              </h2>
              {selectedTask.runtime ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                  <MetadataRow label={t('pages.tasks.runner')} value={selectedTask.runtime.runner_kind} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.directory')} value={selectedTask.runtime.working_directory} fallback={metadataFallback} />
                  <MetadataRow
                    label={t('pages.tasks.command')}
                    value={selectedTask.runtime.command.join(' ') || t('pages.tasks.pendingValue')}
                    fallback={metadataFallback}
                  />
                </div>
              ) : (
                <p className="text-sm text-[var(--text-secondary)]">
                  {t('pages.tasks.runtimeUnavailable')}
                </p>
              )}
            </section>

            <section>
              <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.result')}
              </h2>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                <MetadataRow label={t('pages.tasks.exitCode')} value={selectedTask.result.exit_code} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.failure')} value={selectedTask.result.failure_category} fallback={metadataFallback} />
                <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.result.completed_at} fallback={metadataFallback} />
              </div>
            </section>
          </div>
        </aside>
        )}
      </div>
    </section>
  );
}
