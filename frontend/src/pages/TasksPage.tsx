import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  archiveTask,
  cancelTask,
  forkTask,
  getTask,
  getTasks,
  moveTask,
  retryTask,
  unarchiveTask,
} from '@/shared/api';
import { Button, Checkbox, Dialog, FormField, NativeSelect, PageHeader, PageShell, SplitPane, Textarea, useToast } from '@design-system';
import { useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import type { TaskListResponse, TaskSummary } from '@/shared/types';
import { useAuth } from '@features/auth';
import {
  getDomainProjectContext,
  getDomainProjects,
  getDomainWorkspaces,
} from '@features/domain';
import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import TaskActionsMenu from '@features/tasks/components/TaskActionsMenu';
import TaskInspectorPanel, { type TaskDrawerView } from '@features/tasks/components/TaskInspectorPanel';
import TaskDetailPage from '@features/tasks/pages/TaskDetailPage';
import TaskList from '@features/tasks/pages/TaskList';
import { useTaskStream } from '@features/tasks/hooks/useTaskStream';
import { queryKeys } from '@/shared/api/queryKeys';
import { createIdempotencyKey } from '@/shared/api/idempotency';

const SIDEBAR_COLLAPSED_WIDTH = 0;
const DEFAULT_TASK_SIDEBAR_WIDTH = 320;
const DEFAULT_METADATA_SIDEBAR_WIDTH = 320;
const DRAWER_VIEWS = new Set<TaskDrawerView>(['details', 'attempts', 'context', 'closed']);

function usePageVisibility(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return visible;
}

function TasksPage() {
  const t = useT();
  const { showToast } = useToast();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showArchived, setShowArchived] = useState(false);
  const [taskSort, setTaskSort] = useState<'updated' | 'created' | 'name'>('updated');
  const pageVisible = usePageVisibility();
  const [streamConnected, setStreamConnected] = useState(false);
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks.list(showArchived, taskSort),
    queryFn: () => getTasks({ includeArchived: showArchived, limit: 200, sort: taskSort }),
    refetchInterval: pageVisible && !streamConnected ? 15_000 : false,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskSidebarWidth, setTaskSidebarWidth] = useState(DEFAULT_TASK_SIDEBAR_WIDTH);
  const [taskSidebarCollapsed, setTaskSidebarCollapsed] = useState(false);
  const [metadataSidebarWidth, setMetadataSidebarWidth] = useState(DEFAULT_METADATA_SIDEBAR_WIDTH);
  const [operationDialog, setOperationDialog] = useState<'move' | 'fork' | null>(null);
  const [targetProjectId, setTargetProjectId] = useState('');
  const [targetWorkspaceId, setTargetWorkspaceId] = useState('');
  const [forkPrompt, setForkPrompt] = useState('');
  const createButtonRef = useRef<HTMLButtonElement>(null);

  const requestedTaskId = searchParams.get('task');
  const effectiveSelectedTaskId = useMemo(() => {
    if (requestedTaskId && tasks.some((task) => task.task_id === requestedTaskId)) {
      return requestedTaskId;
    }
    return tasks[0]?.task_id ?? null;
  }, [requestedTaskId, tasks]);

  const rawDrawer = searchParams.get('drawer');
  const legacySidebar = searchParams.get('sidebar');
  const drawerView: TaskDrawerView = rawDrawer && DRAWER_VIEWS.has(rawDrawer as TaskDrawerView)
    ? rawDrawer as TaskDrawerView
    : legacySidebar === 'closed' ? 'closed' : 'details';

  const setDrawerView = useCallback((view: TaskDrawerView) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('drawer', view);
      next.delete('sidebar');
      return next;
    });
  }, [setSearchParams]);

  const selectTask = useCallback(
    (taskId: string | null) => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        if (taskId) {
          next.set('task', taskId);
        } else {
          next.delete('task');
        }
        return next;
      });
    },
    [setSearchParams]
  );

  const toggleMetadataSidebar = useCallback(() => {
    setDrawerView(drawerView === 'closed' ? 'details' : 'closed');
  }, [drawerView, setDrawerView]);

  const toggleTaskSidebar = useCallback(() => {
    setTaskSidebarCollapsed((current) => !current);
  }, []);

  useEffect(() => {
    if (effectiveSelectedTaskId && requestedTaskId !== effectiveSelectedTaskId) {
      selectTask(effectiveSelectedTaskId);
    }
  }, [effectiveSelectedTaskId, requestedTaskId, selectTask]);

  useEffect(() => {
    if (rawDrawer !== drawerView || legacySidebar !== null) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set('drawer', drawerView);
        next.delete('sidebar');
        return next;
      }, { replace: true });
    }
  }, [drawerView, legacySidebar, rawDrawer, setSearchParams]);

  const selectedTaskQuery = useQuery({
    queryKey: queryKeys.tasks.detail(effectiveSelectedTaskId),
    queryFn: () => getTask(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
    refetchInterval: pageVisible && !streamConnected ? 15_000 : false,
  });

  const selectedTask = selectedTaskQuery.data ?? null;
  const handleStreamState = useCallback((state: 'idle' | 'connecting' | 'connected' | 'disconnected') => {
    setStreamConnected(state === 'connected');
  }, []);
  const { outputItems, outputError, hasMore, loadMore, isLoadingMore, connectionState } = useTaskStream(
    effectiveSelectedTaskId,
    handleStreamState,
  );

  const domainProjectsQuery = useQuery({
    queryKey: queryKeys.domain.projects(true),
    queryFn: () => getDomainProjects(true),
  });
  const domainWorkspacesQuery = useQuery({
    queryKey: queryKeys.domain.workspaces(false),
    queryFn: () => getDomainWorkspaces(false),
  });

  const archiveMutation = useMutation({
    mutationFn: (taskId: string) => archiveTask(
      taskId,
      createIdempotencyKey(`task.archive.${taskId}`),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.archived(true) });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelTask(
      taskId,
      createIdempotencyKey(`task.cancel.${taskId}`),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.archived(true) });
    },
  });

  const unarchiveMutation = useMutation({
    mutationFn: (taskId: string) => unarchiveTask(
      taskId,
      createIdempotencyKey(`task.unarchive.${taskId}`),
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });

  const retryMutation = useMutation({
    mutationFn: (taskId: string) => retryTask(
      taskId,
      createIdempotencyKey(`task.retry.${taskId}`),
    ),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.taskEdges.byProject('default') });
      selectTask(data.new_task.task_id);
      showToast(t('pages.tasks.retrySuccess'), 'success');
    },
    onError: () => {
      showToast(t('pages.tasks.retryFailed'), 'error');
    },
  });

  const targetContextQuery = useQuery({
    queryKey: queryKeys.domain.projectContext(targetProjectId || null),
    queryFn: () => getDomainProjectContext(targetProjectId),
    enabled: operationDialog === 'move' && targetProjectId !== '',
  });

  const moveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTask || !targetProjectId) throw new Error('Target Project is required');
      const contextVersionId = targetContextQuery.data?.active_version?.context_version_id;
      if (!contextVersionId) throw new Error('Target Project has no active Context Version');
      return moveTask(
        selectedTask.task_id,
        { project_id: targetProjectId, context_version_id: contextVersionId },
        createIdempotencyKey(`task.move.${selectedTask.task_id}`),
      );
    },
    onSuccess: () => {
      setOperationDialog(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
    },
  });

  const forkMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTask || !targetWorkspaceId) throw new Error('Target Workspace is required');
      const workspace = domainWorkspacesQuery.data?.items.find(
        (item) => item.workspace_id === targetWorkspaceId,
      );
      const projectId = targetProjectId
        || workspace?.project_links.find((link) => link.link_status === 'active')?.project_id;
      const task = await forkTask(
        selectedTask.task_id,
        {
          workspace_id: targetWorkspaceId,
          project_id: projectId,
          prompt: forkPrompt.trim() || undefined,
        },
        createIdempotencyKey(`task.fork.${selectedTask.task_id}`),
      );
      return task;
    },
    onSuccess: (task) => {
      setOperationDialog(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      selectTask(task.task_id);
    },
  });

  const tasksError = extractErrorMessage(tasksQuery.error);
  const detailError = extractErrorMessage(selectedTaskQuery.error);
  const selectedProject = domainProjectsQuery.data?.items.find(
    (project) => project.project_id === selectedTask?.project_id,
  ) ?? null;
  const ownsSelectedTask = Boolean(
    selectedTask && user && (user.role === 'admin' || selectedTask.owner_user_id === user.id),
  );
  const canMutateSelectedTask = ownsSelectedTask && selectedProject?.status !== 'archived';
  const mutationDisabledReason = !ownsSelectedTask
    ? 'Only the Task owner or an administrator can change this Task.'
    : selectedProject?.status === 'archived'
      ? 'This Project is archived; execution actions are disabled.'
      : null;

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  const handleTaskCreated = useCallback((task: TaskSummary) => {
    queryClient.setQueryData<TaskListResponse>(
      queryKeys.tasks.list(showArchived, taskSort),
      (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
        total: (current?.total ?? 0) + 1,
        has_more: current?.has_more ?? false,
        next_cursor: current?.next_cursor ?? null,
      }),
    );
    selectTask(task.task_id);
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.task_id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(false) });
  }, [queryClient, selectTask, showArchived, taskSort]);

  const effectiveTaskSidebarWidth = taskSidebarCollapsed
    ? SIDEBAR_COLLAPSED_WIDTH
    : taskSidebarWidth;
  const effectiveMetadataSidebarWidth = drawerView !== 'closed'
    ? metadataSidebarWidth
    : SIDEBAR_COLLAPSED_WIDTH;

  const taskSidebarContent = taskSidebarCollapsed ? null : (
    <>
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
            {t('pages.tasks.sidebarEyebrow')}
          </p>
          <p className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--foreground)]">
            {t('pages.tasks.sidebarTitle')}
          </p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {t('pages.tasks.sidebarCount', { count: tasks.length })}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <NativeSelect
            value={taskSort}
            onChange={(e) => setTaskSort(e.target.value as 'updated' | 'created' | 'name')}
            className="w-full rounded-lg py-1 text-[11px]"
          >
            <option value="updated">{t('pages.tasks.sort.updated')}</option>
            <option value="created">{t('pages.tasks.sort.created')}</option>
            <option value="name">{t('pages.tasks.sort.name')}</option>
          </NativeSelect>
          <label htmlFor="tasks-show-archived" className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--text-tertiary)]">
            <Checkbox
              id="tasks-show-archived"
              checked={showArchived}
              onCheckedChange={(checked) => setShowArchived(checked === true)}
            />
            {t('pages.tasks.actions.showArchived')}
          </label>
        </div>
      </div>

      <TaskList
        tasks={tasks}
        selectedTaskId={effectiveSelectedTaskId}
        tasksError={tasksError}
        searchQuery={taskSearchQuery}
        onSearchQueryChange={setTaskSearchQuery}
        onSelectTask={selectTask}
      />
    </>
  );

  return (
    <>
      <PageShell variant="canvas" className="gap-4 p-3">
        <PageHeader
          eyebrow="Tasks"
          title={t('pages.tasks.sidebarTitle')}
          description="Inspect the current Task conversation and its durable Attempt history."
          actions={(
            <Button ref={createButtonRef} onClick={() => setCreateDialogOpen(true)}>
              <Plus size={16} />
              {t('pages.tasks.newTask')}
            </Button>
          )}
        />
        <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-[var(--osci-color-border)]">
        <SplitPane
          sidebar={taskSidebarContent}
          sidebarWidth={effectiveTaskSidebarWidth}
          onSidebarWidthChange={setTaskSidebarWidth}
          rightSidebar={
            selectedTask && drawerView !== 'closed' ? (
              <TaskInspectorPanel
                task={selectedTask}
                view={drawerView}
                onViewChange={setDrawerView}
              />
            ) : null
          }
          rightSidebarWidth={effectiveMetadataSidebarWidth}
          onRightSidebarWidthChange={setMetadataSidebarWidth}
          sidebarTestId="task-sidebar"
          rightSidebarTestId="task-metadata-sidebar"
          uniformSurface
        >
          <TaskDetailPage
            key={effectiveSelectedTaskId ?? 'none'}
            taskId={effectiveSelectedTaskId}
            selectedTask={selectedTask}
            detailError={detailError}
            outputItems={outputItems}
            outputError={outputError}
            hasMore={hasMore}
            loadMore={loadMore}
            isLoadingMore={isLoadingMore}
            taskSidebarCollapsed={taskSidebarCollapsed}
            metadataSidebarOpen={drawerView !== 'closed'}
            onToggleTaskSidebar={toggleTaskSidebar}
            onToggleMetadataSidebar={toggleMetadataSidebar}
            headerActions={selectedTask ? (
              <TaskActionsMenu
                task={selectedTask}
                canMutate={canMutateSelectedTask}
                disabledReason={mutationDisabledReason}
                onArchive={() => archiveMutation.mutate(selectedTask.task_id)}
                onUnarchive={() => unarchiveMutation.mutate(selectedTask.task_id)}
                onCancel={() => cancelMutation.mutate(selectedTask.task_id)}
                onRetry={() => retryMutation.mutate(selectedTask.task_id)}
                onMove={() => {
                  setTargetProjectId(selectedTask.project_id);
                  setOperationDialog('move');
                }}
                onFork={() => {
                  setTargetProjectId(selectedTask.project_id);
                  setTargetWorkspaceId(selectedTask.workspace_id);
                  setForkPrompt('');
                  setOperationDialog('fork');
                }}
              />
            ) : null}
          />
        </SplitPane>
        </div>
        {connectionState !== 'connected' && effectiveSelectedTaskId ? (
          <p className="text-xs text-[var(--osci-color-text-muted)]">
            Task stream {connectionState}; visible-page metadata fallback refreshes every 15 seconds.
          </p>
        ) : null}
      </PageShell>

      <TaskCreateFlow
        isOpen={isCreateDialogOpen}
        source="global"
        onClose={closeCreateDialog}
        onCreated={handleTaskCreated}
      />

      <Dialog
        isOpen={operationDialog !== null}
        onClose={() => setOperationDialog(null)}
        title={operationDialog === 'move' ? 'Move Task' : 'Fork Task'}
        size="md"
      >
        <div className="space-y-4">
          <FormField label="Project">
            <NativeSelect
              aria-label="Target Project"
              value={targetProjectId}
              onChange={(event) => {
                setTargetProjectId(event.target.value);
                setTargetWorkspaceId('');
              }}
            >
              <option value="">Select Project</option>
              {(domainProjectsQuery.data?.items ?? [])
                .filter((project) => project.status === 'active')
                .map((project) => (
                  <option key={project.project_id} value={project.project_id}>{project.name}</option>
                ))}
            </NativeSelect>
          </FormField>
          {operationDialog === 'fork' ? (
            <>
              <FormField label="Workspace">
                <NativeSelect
                  aria-label="Target Workspace"
                  value={targetWorkspaceId}
                  onChange={(event) => setTargetWorkspaceId(event.target.value)}
                >
                  <option value="">Select Workspace</option>
                  {(domainWorkspacesQuery.data?.items ?? [])
                    .filter((workspace) => workspace.can_execute && workspace.project_links.some(
                      (link) => link.project_id === targetProjectId && link.link_status === 'active',
                    ))
                    .map((workspace) => (
                      <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.label}</option>
                    ))}
                </NativeSelect>
              </FormField>
              <FormField label="Fork prompt">
                <Textarea
                  aria-label="Fork prompt"
                  value={forkPrompt}
                  onChange={(event) => setForkPrompt(event.target.value)}
                  placeholder="Optional replacement prompt"
                />
              </FormField>
            </>
          ) : (
            <p className="text-sm text-[var(--osci-color-text-muted)]">
              The Task ID, Workspace, and Attempt history remain unchanged. The target Project active Context Version will be pinned.
            </p>
          )}
          {moveMutation.error instanceof Error ? <p className="text-sm text-[var(--osci-color-danger)]">{moveMutation.error.message}</p> : null}
          {forkMutation.error instanceof Error ? <p className="text-sm text-[var(--osci-color-danger)]">{forkMutation.error.message}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOperationDialog(null)}>Cancel</Button>
            <Button
              onClick={() => operationDialog === 'move' ? moveMutation.mutate() : forkMutation.mutate()}
              disabled={operationDialog === 'move'
                ? !targetContextQuery.data?.active_version?.context_version_id
                : !targetProjectId || !targetWorkspaceId}
              isLoading={moveMutation.isPending || forkMutation.isPending}
            >
              {operationDialog === 'move' ? 'Move Task' : 'Fork Task'}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}

export default TasksPage;
