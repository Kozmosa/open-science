import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createTask, getTask, getTasks, getWorkspaces } from '../api';
import { useEnvironmentSelection } from '../components';
import { createEmptyEnvironmentTaskDefaults, useSettings } from '../settings';
import type { TaskCreateRequest, TaskSummary } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';
import TaskList from './tasks/TaskList';
import { useTaskOutputStream } from './tasks/useTaskOutputStream';

function TasksPage() {
  const queryClient = useQueryClient();
  const environmentSelection = useEnvironmentSelection();
  const { settings } = useSettings();
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: getWorkspaces });
  const tasksQuery = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 5000,
  });

  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const environments = environmentSelection.environments;
  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);

  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>('');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [draftResetVersion, setDraftResetVersion] = useState(0);

  const effectiveSelectedTaskId = useMemo(() => {
    if (selectedTaskId && tasks.some((task) => task.task_id === selectedTaskId)) {
      return selectedTaskId;
    }
    return tasks[0]?.task_id ?? null;
  }, [selectedTaskId, tasks]);

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
      queryClient.setQueryData<{ items: TaskSummary[] }>(['tasks'], (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
      }));
      setSelectedTaskId(task.task_id);
      setDraftResetVersion((current) => current + 1);
      void queryClient.invalidateQueries({ queryKey: ['task', task.task_id] });
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
        ? settings.projectDefaults.default.environmentDefaults[
            environmentSelection.selectedEnvironmentId
          ]
        : null) ?? createEmptyEnvironmentTaskDefaults();

    return {
      title: environmentDefaults.titleTemplate,
      task_input: environmentDefaults.taskInputTemplate,
    };
  }, [environmentSelection.selectedEnvironmentId, settings.projectDefaults.default.environmentDefaults]);

  const createError = createMutation.error instanceof Error ? createMutation.error.message : null;
  const tasksError = tasksQuery.error instanceof Error ? tasksQuery.error.message : null;
  const detailError = selectedTaskQuery.error instanceof Error ? selectedTaskQuery.error.message : null;

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          Task Harness
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          Task Harness v1
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          Create Claude Code tasks against a workspace and environment binding, then inspect the
          persisted prompt, runtime payload, replayed output, and final result.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="space-y-6 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
          <div className="space-y-1">
            <h2
              className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              Create task
            </h2>
            <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
              Workspace and environment are selected per task. The backend derives a title when the
              title field is left empty.
            </p>
          </div>

          <TaskCreateForm
            key={`${effectiveEnvironmentId}:${draftResetVersion}`}
            workspaces={workspaces}
            environments={environments}
            selectedWorkspaceId={effectiveWorkspaceId}
            selectedEnvironmentId={effectiveEnvironmentId}
            selectedWorkspace={selectedWorkspace}
            selectedEnvironment={selectedEnvironment}
            draftDefaults={draftDefaults}
            isSubmitting={createMutation.isPending}
            createError={createError}
            onSelectWorkspace={setSelectedWorkspaceId}
            onSelectEnvironment={environmentSelection.onSelectEnvironment}
            onSubmit={(payload) => createMutation.mutate(payload)}
          />

          <TaskList
            tasks={tasks}
            selectedTaskId={effectiveSelectedTaskId}
            tasksError={tasksError}
            onSelectTask={setSelectedTaskId}
          />
        </section>

        <TaskDetail
          selectedTask={selectedTask}
          detailError={detailError}
          outputItems={outputItems}
          outputError={outputError}
        />
      </div>
    </div>
  );
}

export default TasksPage;
