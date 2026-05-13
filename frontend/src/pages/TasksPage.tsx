import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  archiveTask,
  cancelTask,
  createTask,
  deleteTask,
  getProjects,
  getSkills,
  getTask,
  getTasks,
  getWorkspaces,
} from '../api';
import { Button, Modal } from '../components/ui';
import { useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import { SplitPane } from '../components/layout';
import { createEmptyEnvironmentTaskDefaults, useSettings } from '../settings';
import { extractErrorMessage } from '../utils/error';
import type { TaskCreateRequest, TaskSummary } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';
import TaskList from './tasks/TaskList';
import { useTaskOutputStream } from './tasks/useTaskOutputStream';


function TasksPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const environmentSelection = useEnvironmentSelection();
  const { settings } = useSettings();
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: getWorkspaces });
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const skillsQuery = useQuery({ queryKey: ['skills'], queryFn: getSkills });
  const [showArchived, setShowArchived] = useState(false);
  const tasksQuery = useQuery({
    queryKey: ['tasks', showArchived],
    queryFn: () => getTasks(showArchived),
    refetchInterval: 5000,
  });

  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const environments = environmentSelection.environments;
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const availableSkills = useMemo(() => skillsQuery.data?.items ?? [], [skillsQuery.data]);
  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);

  const defaultProjectSettings = settings.projectDefaults.default;
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>(
    defaultProjectSettings?.defaultWorkspaceId ??
      defaultProjectSettings?.selection?.lastWorkspaceId ??
      ''
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string>('default');
  const [draftResetVersion, setDraftResetVersion] = useState(0);
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
  const { outputItems, outputError } = useTaskOutputStream(effectiveSelectedTaskId);

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreateRequest) => createTask(payload),
    onSuccess: (task) => {
      queryClient.setQueryData<{ items: TaskSummary[] }>(['tasks', showArchived], (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
      }));
      selectTask(task.task_id);
      closeCreateDialog();
      setDraftResetVersion((current) => current + 1);
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
      queryClient.setQueryData<{ items: TaskSummary[] }>(
        ['tasks', showArchived],
        (current) => ({
          items: (current?.items ?? []).filter((item) => item.task_id !== taskId),
        })
      );
      if (effectiveSelectedTaskId === taskId) {
        selectTask(null);
      }
    },
  });

  const effectiveWorkspaceId = selectedWorkspaceId || workspaces[0]?.workspace_id || '';
  const effectiveEnvironmentId = environmentSelection.selectedEnvironmentId || environments[0]?.id || '';
  const selectedWorkspace =
    workspaces.find((workspace) => workspace.workspace_id === effectiveWorkspaceId) ?? null;
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const draftDefaults = useMemo(() => {
    const environmentDefaults =
      (environmentSelection.selectedEnvironmentId
        ? settings.projectDefaults.default?.environmentDefaults?.[
            environmentSelection.selectedEnvironmentId
          ]
        : null) ?? createEmptyEnvironmentTaskDefaults();

    return {
      title: environmentDefaults.titleTemplate,
      task_input: environmentDefaults.taskInputTemplate,
      researchAgentProfileId: environmentDefaults.researchAgentProfileId,
      taskConfigurationId: environmentDefaults.taskConfigurationId,
    };
  }, [environmentSelection.selectedEnvironmentId, settings.projectDefaults.default?.environmentDefaults]);

  const createError = extractErrorMessage(createMutation.error);
  const tasksError = extractErrorMessage(tasksQuery.error);
  const detailError = extractErrorMessage(selectedTaskQuery.error);

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  return (
    <>
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
        />
      </SplitPane>

      <Modal
        isOpen={isCreateDialogOpen}
        onClose={closeCreateDialog}
        title={null}
        ariaLabel={t('pages.tasks.createTitle')}
        size="lg"
      >
        <TaskCreateForm
          key={`${effectiveEnvironmentId}:${draftResetVersion}`}
          workspaces={workspaces}
          environments={environments}
          projects={projects}
          selectedWorkspaceId={effectiveWorkspaceId}
          selectedEnvironmentId={effectiveEnvironmentId}
          selectedProjectId={selectedProjectId}
          selectedWorkspace={selectedWorkspace}
          selectedEnvironment={selectedEnvironment}
          draftDefaults={draftDefaults}
          researchAgentProfiles={settings.taskConfiguration.researchAgentProfiles}
          taskConfigurations={settings.taskConfiguration.taskConfigurations}
          availableSkills={availableSkills}
          isSubmitting={createMutation.isPending}
          createError={createError}
          onSelectWorkspace={setSelectedWorkspaceId}
          onSelectEnvironment={environmentSelection.onSelectEnvironment}
          onSelectProject={setSelectedProjectId}
          onSubmit={(payload) => createMutation.mutate(payload)}
          onClose={closeCreateDialog}
        />
      </Modal>
    </>
  );
}

export default TasksPage;
