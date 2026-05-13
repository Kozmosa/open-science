import { useRef, useState } from 'react';
import { Alert } from '../../components/ui';
import { useT } from '../../i18n';
import type { TaskOutputEvent, TaskRecord } from '../../types';
import { statusClassName } from './status';
import MessageStream from './MessageStream';
import TaskInputBar from './TaskInputBar';
import { useTaskMessages } from './useTaskMessages';
import { useTaskActions } from './useTaskActions';
import PromptEditor from './PromptEditor';


interface Props {
  selectedTask: TaskRecord | null;
  detailError: string | null;
  outputItems: TaskOutputEvent[];
  outputError: string | null;
}

function PromptLayerItem({ layer }: { layer: { name: string; label: string; char_count: number; content: string } }) {
  const t = useT();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <details
      className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
    >
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[var(--text)]">
        {layer.label}{' '}
        <span className="text-[var(--text-secondary)]">
          ({layer.char_count} {t('pages.tasks.chars')})
        </span>
      </summary>
      {isOpen && <PromptEditor content={layer.content} />}
    </details>
  );
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
    <div className="flex items-start gap-2 border-b border-[var(--border)] py-2 last:border-0">
      <span className="w-16 shrink-0 text-xs text-[var(--text-secondary)]">{label}</span>
      <span
        className="min-w-0 flex-1 truncate text-right text-xs font-medium text-[var(--text)]"
        title={value ? String(value) : fallback}
      >
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
  const metadataFallback = t('pages.tasks.unavailable');

  const taskId = selectedTask?.task_id ?? null;
  const { messages } = useTaskMessages(taskId, outputItems);

  const MIN_WIDTH = 48;
  const DEFAULT_WIDTH = 320;

  const [asideWidth, setAsideWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const actions = useTaskActions(taskId);

  const handlePointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    setIsDragging(true);
    const startX = e.clientX;
    const startWidth = asideWidth;

    const onMove = (moveEvent: PointerEvent) => {
      const delta = startX - moveEvent.clientX;
      const newWidth = startWidth + delta;
      const clamped = Math.max(MIN_WIDTH, newWidth);
      if (containerRef.current) {
        const maxWidth = containerRef.current.getBoundingClientRect().width - MIN_WIDTH;
        setAsideWidth(Math.min(maxWidth, clamped));
      }
    };

    const onUp = () => {
      setIsDragging(false);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const toggleCollapse = (direction: 'left' | 'right') => {
    if (isDragging) return;
    const container = containerRef.current;
    if (!container) return;
    const maxWidth = container.getBoundingClientRect().width - MIN_WIDTH;

    if (direction === 'left') {
      // ◀ button: collapse main panel, expand aside to max
      if (asideWidth >= maxWidth - 10) {
        setAsideWidth(DEFAULT_WIDTH);
      } else {
        setAsideWidth(maxWidth);
      }
    } else {
      // ▶ button: collapse aside panel, shrink aside to min
      if (asideWidth <= MIN_WIDTH + 10) {
        setAsideWidth(DEFAULT_WIDTH);
      } else {
        setAsideWidth(MIN_WIDTH);
      }
    }
  };

  // Determine if input bar should show
  const showInput = selectedTask &&
    selectedTask.execution_engine === 'agent-sdk' &&
    (selectedTask.status === 'running' || selectedTask.status === 'succeeded' || selectedTask.status === 'paused');

  // Determine pause/resume buttons
  const showPause = selectedTask?.status === 'running' && selectedTask?.execution_engine === 'agent-sdk';
  const showResume = selectedTask?.status === 'paused';

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
              {selectedTask.workspace_summary.label} &middot; {selectedTask.environment_summary.alias} &middot;{' '}
              {selectedTask.environment_summary.display_name}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {showPause && (
              <button
                onClick={() => actions.pause()}
                className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
              >
                Pause
              </button>
            )}
            {showResume && (
              <button
                onClick={() => actions.resume()}
                className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
              >
                Resume
              </button>
            )}
            <span className={`rounded-full border px-3 py-1 text-xs font-medium ${statusClassName[selectedTask.status]}`}>
              {t(`pages.tasks.status.${selectedTask.status}`)}
            </span>
          </div>
        </div>
        {selectedTask.error_summary ? (
          <Alert variant="error" className="mt-3">
            {selectedTask.error_summary}
          </Alert>
        ) : null}
      </header>

      <div ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden">
        <main className="min-h-0 min-w-0 flex-1 flex flex-col bg-[var(--surface)]">
            {/* Message stream area */}
            <div className="flex-1 overflow-hidden">
              {outputError ? <p className="text-sm text-[#ff3b30] p-4">{outputError}</p> : null}
              <MessageStream messages={messages} />
            </div>

            {/* Input bar */}
            {showInput && (
              <TaskInputBar
                onSubmit={actions.sendPrompt}
                disabled={actions.isPending}
              />
            )}

          </main>

        <div
          className="group relative w-[6px] shrink-0 cursor-col-resize select-none touch-none"
          onPointerDown={handlePointerDown}
        >
          <div className="absolute inset-y-0 left-1/2 w-[1px] -translate-x-1/2 bg-[var(--border)]" />

          <div
            className={[
              'absolute top-4 left-1/2 -translate-x-1/2 flex flex-col gap-1 transition-opacity',
              isDragging ? 'opacity-0' : 'opacity-0 group-hover:opacity-100',
            ].join(' ')}
          >
            <button
              onClick={(e) => { e.stopPropagation(); toggleCollapse('left'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title="Show only details"
            >
              ◀
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); toggleCollapse('right'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title="Show only conversation"
            >
              ▶
            </button>
          </div>
        </div>

        <aside
          style={{
            width: asideWidth,
            transition: isDragging ? 'none' : 'width 300ms ease-in-out',
          }}
          className="min-h-0 min-w-0 shrink-0 overflow-x-hidden overflow-y-auto border-t border-[var(--border)] bg-[var(--bg)] p-5 lg:border-t-0"
        >
            <div className="mb-2">
              <h2 className="text-sm font-semibold text-[var(--text)]">
                {t('pages.tasks.summary')}
              </h2>
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

              <section>
                <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
                  {t('pages.tasks.prompt')}
                </h2>
                {selectedTask.prompt ? (
                  <div className="space-y-2">
                    {selectedTask.prompt.layers.map((layer) => (
                      <PromptLayerItem key={layer.name} layer={layer} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-[var(--text-secondary)]">
                    {t('pages.tasks.promptUnavailable')}
                  </p>
                )}
              </section>
            </div>
          </aside>
      </div>
    </section>
  );
}
