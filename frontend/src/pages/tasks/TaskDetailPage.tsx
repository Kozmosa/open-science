import { useT } from '../../i18n';
import { useTaskActions } from './useTaskActions';
import { useTaskMessages } from './useTaskMessages';
import MessageList from '../../components/messages/MessageList';
import TaskHeaderBar from '../../components/messages/TaskHeaderBar';
import TaskInputBar from './TaskInputBar';
import type { TaskOutputEvent, TaskRecord } from '../../types';

const interactiveEngines = new Set(['claude-code', 'agent-sdk', 'codex-app-server']);

interface TaskDetailPageProps {
  taskId: string | null;
  selectedTask: TaskRecord | null;
  detailError: string | null;
  outputItems: TaskOutputEvent[];
  outputError: string | null;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  metadataSidebarOpen?: boolean;
  onToggleMetadataSidebar?: () => void;
}

export default function TaskDetailPage({
  taskId,
  selectedTask,
  detailError,
  outputItems,
  outputError,
  hasMore,
  loadMore,
  isLoadingMore,
  metadataSidebarOpen = true,
  onToggleMetadataSidebar = () => {},
}: TaskDetailPageProps) {
  const t = useT();
  const { messages, isLoading, error } = useTaskMessages(taskId, outputItems, selectedTask?.prompt ?? null);
  const actions = useTaskActions(taskId);

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
          <h2 className="text-base font-semibold text-[var(--text)]">{t('pages.tasks.noTaskSelected')}</h2>
          <p className="mt-2 text-sm text-[var(--text-secondary)]">{t('pages.tasks.noTaskSelectedDescription')}</p>
        </div>
      </section>
    );
  }

  const engine = selectedTask.harness_engine ?? selectedTask.execution_engine ?? '';
  const showInput =
    interactiveEngines.has(engine) &&
    (selectedTask.status === 'running' ||
      selectedTask.status === 'succeeded' ||
      selectedTask.status === 'paused' ||
      selectedTask.status === 'failed');
  const showPause = selectedTask.status === 'running' && interactiveEngines.has(engine);
  const showResume = selectedTask.status === 'paused' && interactiveEngines.has(engine);

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[var(--surface)]">
      <TaskHeaderBar
        task={selectedTask}
        onToggleDrawer={onToggleMetadataSidebar}
        metadataSidebarOpen={metadataSidebarOpen}
        showPause={showPause}
        showResume={showResume}
        onPause={() => actions.pause()}
        onResume={() => actions.resume()}
      />

      {outputError && (
        <div className="shrink-0 border-b border-[var(--danger-border)] bg-[var(--danger-soft)] px-4 py-2 text-xs text-[var(--danger-foreground)]">
          {outputError}
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {isLoading && messages.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--text-tertiary)]">
            loading messages…
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--danger)]">
            {error instanceof Error ? error.message : String(error)}
          </div>
        ) : (
          <MessageList
            messages={messages}
            hasMore={hasMore}
            loadMore={loadMore}
            isLoadingMore={isLoadingMore}
          />
        )}
      </div>

      {showInput && <TaskInputBar onSubmit={actions.sendPrompt} disabled={actions.isPending} />}
    </section>
  );
}
