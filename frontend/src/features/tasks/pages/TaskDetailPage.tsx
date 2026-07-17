import { useT } from '@/shared/i18n';
import { useTaskActions } from '../hooks/useTaskActions';
import { useTaskMessages } from '../hooks/useTaskMessages';
import { groupMessages, ChatInputBar, ChatMessageList } from '@/components/chat';
import TaskHeaderBar from '@/components/messages/TaskHeaderBar';
import type { ReactNode } from 'react';
import type { TaskOutputEvent, TaskRecord } from '@/shared/types';

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
  taskSidebarCollapsed?: boolean;
  metadataSidebarOpen?: boolean;
  onToggleTaskSidebar?: () => void;
  onToggleMetadataSidebar?: () => void;
  onBackToList?: () => void;
  canMutate?: boolean;
  mutationDisabledReason?: string | null;
  headerActions?: ReactNode;
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
  taskSidebarCollapsed = false,
  metadataSidebarOpen = true,
  onToggleTaskSidebar,
  onToggleMetadataSidebar,
  onBackToList,
  canMutate = false,
  mutationDisabledReason = null,
  headerActions,
}: TaskDetailPageProps) {
  const t = useT();
  const { messages, isLoading, error } = useTaskMessages(taskId, outputItems, selectedTask?.prompt ?? null);
  const actions = useTaskActions(taskId);
  const chatMessages = groupMessages(messages);

  if (detailError) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center p-6">
        <p className="text-sm text-[var(--osci-color-danger)]">{detailError}</p>
      </section>
    );
  }

  if (!selectedTask) {
    return (
      <section className="flex min-h-0 flex-1 items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <h2 className="text-base font-semibold text-[var(--osci-color-text)]">{t('pages.tasks.noTaskSelected')}</h2>
          <p className="mt-2 text-sm text-[var(--osci-color-text-secondary)]">{t('pages.tasks.noTaskSelectedDescription')}</p>
        </div>
      </section>
    );
  }

  const engine = selectedTask.harness_engine ?? selectedTask.execution_engine ?? '';
  const showInput =
    canMutate &&
    !selectedTask.archived_at &&
    interactiveEngines.has(engine) &&
    (selectedTask.status === 'running' ||
      selectedTask.status === 'succeeded' ||
      selectedTask.status === 'paused' ||
      selectedTask.status === 'failed');
  const showPause = canMutate && selectedTask.status === 'running' && interactiveEngines.has(engine);
  const showResume = canMutate && selectedTask.status === 'paused' && interactiveEngines.has(engine);

  return (
    <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-[var(--osci-color-surface)]">
      <TaskHeaderBar
        task={selectedTask}
        showPause={showPause}
        showResume={showResume}
        onPause={() => actions.pause()}
        onResume={() => actions.resume()}
        taskSidebarCollapsed={taskSidebarCollapsed}
        metadataSidebarOpen={metadataSidebarOpen}
        onToggleTaskSidebar={onToggleTaskSidebar}
        onToggleMetadataSidebar={onToggleMetadataSidebar}
        onBackToList={onBackToList}
        canRename={canMutate}
        mutationDisabledReason={mutationDisabledReason}
        actions={headerActions}
      />

      {outputError && (
        <div className="shrink-0 border-b border-[var(--osci-color-danger-border)] bg-[var(--osci-color-danger-soft)] px-4 py-2 text-xs text-[var(--osci-color-danger-foreground)]">
          {outputError}
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {isLoading && messages.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--osci-color-text-muted)]">
            loading messages…
          </div>
        ) : error ? (
          <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--osci-color-danger)]">
            {error instanceof Error ? error.message : String(error)}
          </div>
        ) : (
          <ChatMessageList
            messages={chatMessages}
            hasMore={hasMore}
            loadMore={loadMore}
            isLoadingMore={isLoadingMore}
          />
        )}
      </div>

      {showInput && (
        <div className="absolute bottom-0 left-0 right-0 pointer-events-none">
          <ChatInputBar onSubmit={actions.sendPrompt} disabled={actions.isPending} />
        </div>
      )}
      {!canMutate && mutationDisabledReason ? (
        <p className="shrink-0 border-t border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] px-4 py-2 text-xs text-[var(--osci-color-text-muted)]">
          {mutationDisabledReason}
        </p>
      ) : null}
    </section>
  );
}
