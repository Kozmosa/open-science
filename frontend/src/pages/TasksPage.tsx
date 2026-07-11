import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  archiveTask,
  cancelTask,
  createTask,
  deleteTask,
  getEnvironments,
  getProjects,
  getSkills,
  getTask,
  getTasks,
  getWorkspaces,
  retryTask,
} from '@/shared/api';
import { Button, Modal, Select } from '@design-system/primitives';
import { useToast } from '../components/common/Toast';
import { useT } from '@/shared/i18n';
import { PageShell, SplitPane } from '@design-system/layout';
import { extractErrorMessage } from '@/shared/utils/error';
import { useAuth } from '@features/auth';
import type { TaskCreatePayload, TaskListResponse } from '@/shared/types';
import TaskCreateForm from '@features/tasks/components/TaskCreateForm';
import TaskDetailPage from '@features/tasks/pages/TaskDetailPage';
import TaskList from '@features/tasks/pages/TaskList';
import TaskMetadataDrawer from '../components/messages/TaskMetadataDrawer';
import { useTaskStream } from '@features/tasks/hooks/useTaskStream';
import { queryKeys } from '@/shared/api/queryKeys';

const SIDEBAR_COLLAPSED_WIDTH = 0;
const DEFAULT_TASK_SIDEBAR_WIDTH = 320;
const DEFAULT_METADATA_SIDEBAR_WIDTH = 320;

function TasksPage() {
  const t = useT();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showArchived, setShowArchived] = useState(false);
  const [taskSort, setTaskSort] = useState<'updated' | 'created' | 'name'>('updated');
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks.list(showArchived, taskSort),
    queryFn: () => getTasks({ includeArchived: showArchived, limit: 200, sort: taskSort }),
    refetchInterval: 5000,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskSidebarWidth, setTaskSidebarWidth] = useState(DEFAULT_TASK_SIDEBAR_WIDTH);
  const [taskSidebarCollapsed, setTaskSidebarCollapsed] = useState(false);
  const [metadataSidebarWidth, setMetadataSidebarWidth] = useState(DEFAULT_METADATA_SIDEBAR_WIDTH);
  const createButtonRef = useRef<HTMLButtonElement>(null);

  const requestedTaskId = searchParams.get('task');
  const effectiveSelectedTaskId = useMemo(() => {
    if (requestedTaskId && tasks.some((task) => task.task_id === requestedTaskId)) {
      return requestedTaskId;
    }
    return tasks[0]?.task_id ?? null;
  }, [requestedTaskId, tasks]);

  const metadataSidebarOpen = searchParams.get('sidebar') !== 'closed';

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
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (metadataSidebarOpen) {
        next.set('sidebar', 'closed');
      } else {
        next.set('sidebar', 'open');
      }
      return next;
    });
  }, [metadataSidebarOpen, setSearchParams]);

  const toggleTaskSidebar = useCallback(() => {
    setTaskSidebarCollapsed((current) => !current);
  }, []);

  useEffect(() => {
    if (effectiveSelectedTaskId && requestedTaskId !== effectiveSelectedTaskId) {
      selectTask(effectiveSelectedTaskId);
    }
  }, [effectiveSelectedTaskId, requestedTaskId, selectTask]);

  const selectedTaskQuery = useQuery({
    queryKey: queryKeys.tasks.detail(effectiveSelectedTaskId),
    queryFn: () => getTask(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
    refetchInterval: 5000,
  });

  const selectedTask = selectedTaskQuery.data ?? null;
  const { outputItems, outputError, hasMore, loadMore, isLoadingMore } = useTaskStream(effectiveSelectedTaskId);

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreatePayload) => createTask(payload),
    onSuccess: (task) => {
      queryClient.setQueryData<TaskListResponse>(queryKeys.tasks.list(showArchived, taskSort), (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
        total: (current?.total ?? 0) + 1,
        has_more: current?.has_more ?? false,
        next_cursor: current?.next_cursor ?? null,
      }));
      selectTask(task.task_id);
      closeCreateDialog();
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.task_id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject('default') });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (taskId: string) => archiveTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.archived(true) });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.archived(true) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(taskId),
    onSuccess: (_data, taskId) => {
      queryClient.setQueryData<TaskListResponse>(
        queryKeys.tasks.list(showArchived, taskSort),
        (current) => ({
          items: (current?.items ?? []).filter((item) => item.task_id !== taskId),
          total: current?.total != null ? current.total - 1 : undefined,
          has_more: current?.has_more ?? false,
          next_cursor: current?.next_cursor ?? null,
        })
      );
      if (effectiveSelectedTaskId === taskId) {
        selectTask(null);
      }
    },
  });

  const retryMutation = useMutation({
    mutationFn: (taskId: string) => retryTask(taskId),
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

  // Fetch defaults for task creation
  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.all,
    queryFn: getProjects,
  });
  const workspacesQuery = useQuery({
    queryKey: queryKeys.workspaces.all,
    queryFn: getWorkspaces,
  });
  const environmentsQuery = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: getEnvironments,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.all,
    queryFn: getSkills,
  });


  const { user } = useAuth();
  const defaultProjectId = useMemo(() => {
    const items = projectsQuery.data?.items;
    if (user) {
      const userDefault = items?.find((p) => p.project_id === `${user.username}_default`);
      if (userDefault) return userDefault.project_id;
    }
    return items?.[0]?.project_id ?? '';
  }, [user, projectsQuery.data]);
  const defaultWorkspaceId = workspacesQuery.data?.items?.[0]?.workspace_id ?? '';
  const defaultEnvironmentId = environmentsQuery.data?.items?.[0]?.id ?? '';
  const availableProjects = projectsQuery.data?.items ?? [];
  const availableWorkspaces = workspacesQuery.data?.items ?? [];
  const availableEnvironments = environmentsQuery.data?.items ?? [];

  const tasksError = extractErrorMessage(tasksQuery.error);
  const detailError = extractErrorMessage(selectedTaskQuery.error);

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  const effectiveTaskSidebarWidth = taskSidebarCollapsed
    ? SIDEBAR_COLLAPSED_WIDTH
    : taskSidebarWidth;
  const effectiveMetadataSidebarWidth = metadataSidebarOpen
    ? metadataSidebarWidth
    : SIDEBAR_COLLAPSED_WIDTH;

  const taskSidebarContent = taskSidebarCollapsed ? null : (
    <>
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-tertiary)]">
            {t('pages.tasks.sidebarEyebrow')}
          </p>
          <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--foreground)]">
            {t('pages.tasks.sidebarTitle')}
          </h1>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {t('pages.tasks.sidebarCount', { count: tasks.length })}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button
            ref={createButtonRef}
            onClick={() => setCreateDialogOpen(true)}
            className="inline-flex h-9 shrink-0 items-center rounded-xl px-3 shadow-[var(--shadow-sm)] transition-all active:scale-[0.98]"
          >
            <Plus size={15} className="shrink-0" />
            <span
              className={[
                'overflow-hidden whitespace-nowrap transition-all duration-200',
                taskSidebarWidth < 300 ? 'ml-0 max-w-0 opacity-0' : 'ml-2 max-w-[100px] opacity-100',
              ].join(' ')}
            >
              {t('pages.tasks.newTask')}
            </span>
          </Button>
          <Select
            value={taskSort}
            onChange={(e) => setTaskSort(e.target.value as 'updated' | 'created' | 'name')}
            className="w-full rounded-lg py-1 text-[11px]"
          >
            <option value="updated">{t('pages.tasks.sort.updated')}</option>
            <option value="created">{t('pages.tasks.sort.created')}</option>
            <option value="name">{t('pages.tasks.sort.name')}</option>
          </Select>
          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--text-tertiary)]">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
              className="rounded border-[var(--border)] accent-[var(--prism-primary)]"
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
        showArchived={showArchived}
        onSearchQueryChange={setTaskSearchQuery}
        onSelectTask={selectTask}
        onArchiveTask={(taskId) => archiveMutation.mutate(taskId)}
        onCancelTask={(taskId) => cancelMutation.mutate(taskId)}
        onDeleteTask={(taskId) => deleteMutation.mutate(taskId)}
        onRetryTask={(taskId) => retryMutation.mutate(taskId)}
      />
    </>
  );

  return (
    <>
      <PageShell className="p-3">
        <SplitPane
          sidebar={taskSidebarContent}
          sidebarWidth={effectiveTaskSidebarWidth}
          onSidebarWidthChange={setTaskSidebarWidth}
          rightSidebar={
            selectedTask ? (
              <TaskMetadataDrawer
                task={selectedTask}
              />
            ) : null
          }
          rightSidebarWidth={effectiveMetadataSidebarWidth}
          onRightSidebarWidthChange={setMetadataSidebarWidth}
          sidebarTestId="task-sidebar"
          rightSidebarTestId="task-metadata-sidebar"
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
            metadataSidebarOpen={metadataSidebarOpen}
            onToggleTaskSidebar={toggleTaskSidebar}
            onToggleMetadataSidebar={toggleMetadataSidebar}
          />
        </SplitPane>
      </PageShell>

      <Modal
        isOpen={isCreateDialogOpen}
        onClose={closeCreateDialog}
        title={null}
        ariaLabel={t('pages.tasks.createTitle')}
        size="lg"
      >
        <TaskCreateForm
          projectId={defaultProjectId}
          workspaceId={defaultWorkspaceId}
          environmentId={defaultEnvironmentId}
          availableProjects={availableProjects}
          availableWorkspaces={availableWorkspaces}
          availableEnvironments={availableEnvironments}
          availableSkills={skillsQuery.data?.items ?? []}
          onSubmit={(payload) => createMutation.mutate(payload)}
          onCancel={closeCreateDialog}
        />
      </Modal>
    </>
  );
}

export default TasksPage;
