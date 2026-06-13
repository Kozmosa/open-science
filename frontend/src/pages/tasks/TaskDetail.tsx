import { useRef, useState } from 'react';
import { Alert } from '../../components/ui';
import { useT } from '../../i18n';
import type { TaskOutputEvent, TaskRecord } from '../../types';
import { statusClassName } from './status';
import MessageStream from './MessageStream';
import TaskInputBar from './TaskInputBar';
import { useTaskMessages } from './useTaskMessages';
import { useTaskActions } from './useTaskActions';

const interactiveEngines = new Set(['claude-code', 'agent-sdk', 'codex-app-server']);

interface Props {
  taskId: string | null;
  selectedTask: TaskRecord | null;
  detailError: string | null;
  outputItems: TaskOutputEvent[];
  outputError: string | null;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
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
  taskId,
  selectedTask,
  detailError,
  outputItems,
  outputError,
  hasMore,
  loadMore,
  isLoadingMore,
}: Props) {
  const t = useT();
  const metadataFallback = t('pages.tasks.unavailable');

  const { messages } = useTaskMessages(taskId, outputItems, selectedTask?.prompt ?? null);

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
      if (asideWidth >= maxWidth - 10) {
        setAsideWidth(DEFAULT_WIDTH);
      } else {
        setAsideWidth(maxWidth);
      }
    } else {
      if (asideWidth <= MIN_WIDTH + 10) {
        setAsideWidth(DEFAULT_WIDTH);
      } else {
        setAsideWidth(MIN_WIDTH);
      }
    }
  };

  // Determine if input bar should show
  const engine = selectedTask?.harness_engine ?? selectedTask?.execution_engine ?? '';
  const showInput = selectedTask &&
    interactiveEngines.has(engine) &&
    (selectedTask.status === 'running' || selectedTask.status === 'succeeded' || selectedTask.status === 'paused');

  // Determine pause/resume buttons
  const showPause =
    selectedTask?.status === 'running' &&
    interactiveEngines.has(engine);
  const showResume =
    selectedTask?.status === 'paused' &&
    interactiveEngines.has(engine);
  if (detailError) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center p-6">
        <p className="text-sm text-[var(--danger)]">{detailError}</p>
      </section>
    );
  }

  if (!selectedTask) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center p-6">
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

  const command = selectedTask.command?.length
    ? selectedTask.command.join(' ')
    : selectedTask.runtime?.command?.length
      ? selectedTask.runtime.command.join(' ')
      : null;
  const workingDirectory =
    selectedTask.working_directory ??
    selectedTask.runtime?.working_directory ??
    selectedTask.binding?.resolved_workdir ??
    null;

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <header className="border-b border-[var(--border)] px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              {t('pages.tasks.workspaceEyebrow')}
            </p>
            <h1 className="mt-1 truncate text-xl font-semibold tracking-tight text-[var(--text)]" title={selectedTask.title}>
              {selectedTask.title}
            </h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {selectedTask.researcher_type ?? selectedTask.task_profile ?? 'researcher'} &middot; {selectedTask.harness_engine ?? selectedTask.execution_engine ?? 'claude-code'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {showPause && (
              <button
                type="button"
                onClick={() => actions.pause()}
                className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
              >
                {t('pages.tasks.actions.pause')}
              </button>
            )}
            {showResume && (
              <button
                type="button"
                onClick={() => actions.resume()}
                className="rounded-md bg-[var(--bg-secondary)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
              >
                {t('pages.tasks.actions.resume')}
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
            <div className="flex min-h-0 flex-1 overflow-hidden">
              {outputError ? <p className="p-4 text-sm text-[var(--danger)]">{outputError}</p> : null}
              <MessageStream messages={messages} hasMore={hasMore} loadMore={loadMore} isLoadingMore={isLoadingMore} />
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
              type="button"
              onClick={(e) => { e.stopPropagation(); toggleCollapse('left'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title={t('pages.tasks.layout.showOnlyDetails')}
              aria-label={t('pages.tasks.layout.showOnlyDetails')}
            >
              ◀
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); toggleCollapse('right'); }}
              className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[10px] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)]"
              title={t('pages.tasks.layout.showOnlyConversation')}
              aria-label={t('pages.tasks.layout.showOnlyConversation')}
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
                  <MetadataRow label={t('pages.tasks.metadata.workdir')} value={workingDirectory} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.metadata.command')} value={command} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.metadata.taskInput')} value={selectedTask.prompt ?? selectedTask.binding?.task_input ?? null} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.taskId')} value={selectedTask.task_id} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.created')} value={selectedTask.created_at} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.updated')} value={selectedTask.updated_at} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.started')} value={selectedTask.started_at} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.completed_at} fallback={metadataFallback} />
                </div>
              </section>

              <section>
                <h2 className="mb-2 text-sm font-semibold text-[var(--text)]">
                  {t('pages.tasks.result')}
                </h2>
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3">
                  <MetadataRow label={t('pages.tasks.exitCode')} value={selectedTask.result?.exit_code ?? selectedTask.exit_code ?? null} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.failure')} value={selectedTask.result?.failure_category ?? null} fallback={metadataFallback} />
                  <MetadataRow label={t('pages.tasks.completed')} value={selectedTask.result?.completed_at ?? selectedTask.completed_at ?? null} fallback={metadataFallback} />
                </div>
              </section>
            </div>
          </aside>
      </div>
    </section>
  );
}
