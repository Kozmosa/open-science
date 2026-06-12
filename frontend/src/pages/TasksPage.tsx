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
} from '../api';
import { Button, Modal, Select } from '../components/ui';
import { useToast } from '../components/common/Toast';
import { useT } from '../i18n';
import { PageShell, SplitPane } from '../components/layout';
import { extractErrorMessage } from '../utils/error';
import { useAuth } from '../contexts/AuthContext';
import type { TaskCreatePayload, TaskListResponse } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';
import TaskList from './tasks/TaskList';
import { useTaskOutputStream } from './tasks/useTaskOutputStream';


function TasksPage() {
  const t = useT();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showArchived, setShowArchived] = useState(false);
  const [taskSort, setTaskSort] = useState<'updated' | 'created' | 'name'>('updated');
  const tasksQuery = useQuery({
    queryKey: ['tasks', showArchived, taskSort],
    queryFn: () => getTasks({ includeArchived: showArchived, limit: 200, sort: taskSort }),
    refetchInterval: 5000,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskSidebarWidth, setTaskSidebarWidth] = useState(320);
  const createButtonRef = useRef<HTMLButtonElement | null>(null);

  const requestedTaskId = searchParams.get('task');
  const effectiveSelectedTaskId = useMemo(() => {
    if (requestedTaskId && tasks.some((task) => task.task_id === requestedTaskId)) {
      return requestedTaskId;
    }
    return tasks[0]?.task_id ?? null;
  }, [requestedTaskId, tasks]);

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

  useEffect(() => {
    if (effectiveSelectedTaskId && requestedTaskId !== effectiveSelectedTaskId) {
      selectTask(effectiveSelectedTaskId);
    }
  }, [effectiveSelectedTaskId, requestedTaskId, selectTask]);

  const selectedTaskQuery = useQuery({
    queryKey: ['task', effectiveSelectedTaskId],
    queryFn: () => getTask(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
    refetchInterval: 5000,
  });

  const selectedTask = selectedTaskQuery.data ?? null;
  const { outputItems, outputError, hasMore, loadMore, isLoadingMore } = useTaskOutputStream(effectiveSelectedTaskId);

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreatePayload) => createTask(payload),
    onSuccess: (task) => {
      queryClient.setQueryData<TaskListResponse>(['tasks', showArchived, taskSort], (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
        total: (current?.total ?? 0) + 1,
        has_more: current?.has_more ?? false,
        next_cursor: current?.next_cursor ?? null,
      }));
      selectTask(task.task_id);
      closeCreateDialog();
      void queryClient.invalidateQueries({ queryKey: ['task', task.task_id] });
      void queryClient.invalidateQueries({ queryKey: ['project-tasks'] });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (taskId: string) => archiveTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      void queryClient.invalidateQueries({ queryKey: ['tasks', true] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      void queryClient.invalidateQueries({ queryKey: ['tasks', true] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(taskId),
    onSuccess: (_data, taskId) => {
      queryClient.setQueryData<TaskListResponse>(
        ['tasks', showArchived, taskSort],
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
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      void queryClient.invalidateQueries({ queryKey: ['task-edges'] });
      selectTask(data.new_task.task_id);
      showToast(t('pages.tasks.retrySuccess'), 'success');
    },
    onError: () => {
      showToast(t('pages.tasks.retryFailed'), 'error');
    },
  });

  // Fetch defaults for task creation
  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
  });
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: getWorkspaces,
  });
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const skillsQuery = useQuery({
    queryKey: ['skills'],
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

  return (
    <>
      <PageShell>
        <SplitPane
        sidebar={
          <>
            <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
                {t('pages.tasks.sidebarEyebrow')}
              </p>
              <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--sidebar-foreground)]">
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
                className="inline-flex h-9 shrink-0 items-center px-3 shadow-sm transition-all"
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
                className="w-full text-[11px] py-1"
              >
                <option value="updated">{t('pages.tasks.sort.updated')}</option>
                <option value="created">{t('pages.tasks.sort.created')}</option>
                <option value="name">{t('pages.tasks.sort.name')}</option>
              </Select>
              <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
                <input
                  type="checkbox"
                  checked={showArchived}
                  onChange={(event) => setShowArchived(event.target.checked)}
                  className="rounded border-[var(--border)]"
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
        </>}
        sidebarWidth={taskSidebarWidth}
        onSidebarWidthChange={setTaskSidebarWidth}
        sidebarTestId="task-sidebar"
      >
        <TaskDetail
          selectedTask={selectedTask}
          detailError={detailError}
          outputItems={outputItems}
          outputError={outputError}
          hasMore={hasMore}
          loadMore={loadMore}
          isLoadingMore={isLoadingMore}
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
