import { useRef, useState, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, GripVertical, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { Alert } from '../../components/ui';
import { useT } from '../../i18n';
import type { TaskOutputEvent, TaskRecord } from '../../types';
import { updateTask } from '../../api';
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

  const DEFAULT_WIDTH = 320;
  const MIN_OPEN_WIDTH = 200;

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [asideWidth, setAsideWidth] = useState(DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const actions = useTaskActions(taskId);

  // ── Inline title editing ──
  const queryClient = useQueryClient();
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const titleInputRef = useRef<HTMLInputElement>(null);

  const renameMutation = useMutation({
    mutationFn: (title: string) => updateTask(taskId!, { title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
    },
  });

  const startEditTitle = useCallback(() => {
    if (!selectedTask) return;
    setEditTitle(selectedTask.title);
    setIsEditingTitle(true);
    // Focus after render
    requestAnimationFrame(() => titleInputRef.current?.focus());
  }, [selectedTask]);

  const commitTitle = useCallback(() => {
    setIsEditingTitle(false);
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== selectedTask?.title) {
      renameMutation.mutate(trimmed);
    }
  }, [editTitle, selectedTask, renameMutation]);

  const cancelEditTitle = useCallback(() => {
    setIsEditingTitle(false);
  }, []);

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    setIsDragging(true);
    const startX = e.clientX;
    const startWidth = asideWidth;

    const onMove = (moveEvent: PointerEvent) => {
      const delta = startX - moveEvent.clientX;
      const newWidth = startWidth + delta;
      const clamped = Math.max(MIN_OPEN_WIDTH, newWidth);
      if (containerRef.current) {
        const maxWidth = containerRef.current.getBoundingClientRect().width - 100;
        setAsideWidth(Math.min(maxWidth, clamped));
      }
    };

    const onUp = () => {
      setIsDragging(false);
      // Auto-close if dragged to near-minimum width
      setAsideWidth((currentWidth) => {
        if (currentWidth <= MIN_OPEN_WIDTH + 20) {
          setSidebarOpen(false);
          return DEFAULT_WIDTH;
        }
        return currentWidth;
      });
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }, [asideWidth]);

  // Determine if input bar should show
  const engine = selectedTask?.harness_engine ?? selectedTask?.execution_engine ?? '';
  const showInput = selectedTask &&
    interactiveEngines.has(engine) &&
    (selectedTask.status === 'running' || selectedTask.status === 'succeeded' || selectedTask.status === 'paused' || selectedTask.status === 'failed');

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
    <section ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden">
      {/* ── Main area: message stream + input bar ── */}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-[var(--surface)]">
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          {outputError ? <p className="p-4 text-sm text-[var(--danger)]">{outputError}</p> : null}
          <MessageStream messages={messages} hasMore={hasMore} loadMore={loadMore} isLoadingMore={isLoadingMore} />

          {/* Always-visible toggle button */}
          <button
            type="button"
            onClick={() => setSidebarOpen((prev) => !prev)}
            className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] shadow-sm transition hover:bg-[var(--border)] hover:text-[var(--text)]"
            title={sidebarOpen ? t('pages.tasks.layout.collapseSidebar') : t('pages.tasks.layout.expandSidebar')}
            aria-label={sidebarOpen ? t('pages.tasks.layout.collapseSidebar') : t('pages.tasks.layout.expandSidebar')}
            aria-expanded={sidebarOpen}
            aria-controls="task-detail-sidebar"
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>

          {/* Error indicator when sidebar is closed */}
          {!sidebarOpen && selectedTask.error_summary && (
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="absolute right-14 top-3 z-10 flex h-8 items-center gap-1.5 rounded-md border border-[var(--danger-border)] bg-[var(--danger-soft)] px-2 text-xs font-medium text-[var(--danger-foreground)] shadow-sm transition hover:opacity-80"
              title={selectedTask.error_summary}
              aria-label={t('pages.tasks.layout.errorIndicator')}
            >
              <AlertTriangle size={12} />
            </button>
          )}
        </div>

        {/* Input bar */}
        {showInput && (
          <TaskInputBar
            onSubmit={actions.sendPrompt}
            disabled={actions.isPending}
          />
        )}
      </main>

      {/* ── Drag handle (visible only when sidebar is open) ── */}
      {sidebarOpen && (
        <div
          className="group relative w-[6px] shrink-0 cursor-col-resize select-none touch-none"
          onPointerDown={handlePointerDown}
          role="separator"
          aria-orientation="vertical"
          aria-label={t('pages.tasks.layout.resizeSidebar')}
          aria-valuenow={asideWidth}
          aria-valuemin={MIN_OPEN_WIDTH}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') {
              setAsideWidth((w) => Math.max(MIN_OPEN_WIDTH, w - 16));
            }
            if (e.key === 'ArrowRight') {
              const maxW = containerRef.current ? containerRef.current.getBoundingClientRect().width - 100 : 800;
              setAsideWidth((w) => Math.min(maxW, w + 16));
            }
          }}
        >
          <div className="absolute inset-y-0 left-1/2 w-[1px] -translate-x-1/2 bg-[var(--border)] transition-colors group-hover:bg-[var(--apple-blue)] group-focus-visible:bg-[var(--apple-blue)]" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex h-8 w-4 items-center justify-center rounded-full bg-[var(--bg-secondary)] text-[var(--text-tertiary)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            <GripVertical size={10} />
          </div>
        </div>
      )}

      {/* ── Right sidebar: header info + metadata ── */}
      <aside
        id="task-detail-sidebar"
        style={{
          width: sidebarOpen ? asideWidth : 0,
          transition: isDragging ? 'none' : 'width 300ms ease-in-out',
          overflow: 'hidden',
        }}
        className="min-h-0 shrink-0 overflow-hidden border-l border-[var(--border)] bg-[var(--bg)]"
        aria-hidden={!sidebarOpen}
      >
        {/* Inner content with fixed width to prevent squishing during close animation */}
        <div className="flex h-full flex-col" style={{ width: sidebarOpen ? asideWidth : DEFAULT_WIDTH }}>
          {/* ── Sidebar Header ── */}
          <div className="shrink-0 border-b border-[var(--border)] px-4 py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                  {t('pages.tasks.workspaceEyebrow')}
                </p>
                {isEditingTitle ? (
                  <input
                    ref={titleInputRef}
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onBlur={commitTitle}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitTitle();
                      if (e.key === 'Escape') cancelEditTitle();
                    }}
                    className="w-full rounded border border-[var(--border)] bg-transparent px-1 py-0.5 text-base font-semibold text-[var(--text)] outline-none focus:border-[var(--primary)]"
                  />
                ) : (
                  <h1
                    className="cursor-pointer truncate rounded px-1 py-0.5 text-base font-semibold tracking-tight text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
                    title={selectedTask.title}
                    onClick={startEditTitle}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') startEditTitle(); }}
                  >
                    {selectedTask.title}
                  </h1>
                )}
                <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
                  {selectedTask.researcher_type ?? selectedTask.task_profile ?? 'researcher'} &middot; {selectedTask.harness_engine ?? selectedTask.execution_engine ?? 'claude-code'}
                </p>
              </div>
              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusClassName[selectedTask.status]}`}>
                {t(`pages.tasks.status.${selectedTask.status}`)}
              </span>
            </div>
            {(showPause || showResume) && (
              <div className="mt-2 flex items-center gap-2">
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
              </div>
            )}
            {selectedTask.error_summary ? (
              <Alert variant="error" className="mt-2">
                {selectedTask.error_summary}
              </Alert>
            ) : null}
          </div>

          {/* ── Sidebar Body (scrollable metadata) ── */}
          <div className="flex-1 overflow-y-auto p-4">
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
          </div>
        </div>
      </aside>
    </section>
  );
}
