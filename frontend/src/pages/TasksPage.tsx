import { Plus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { createTask, getTask, getTasks, getWorkspaces } from '../api';
import { useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import { createEmptyEnvironmentTaskDefaults, useSettings } from '../settings';
import type { TaskCreateRequest, TaskSummary } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';
import TaskList from './tasks/TaskList';
import { useTaskOutputStream } from './tasks/useTaskOutputStream';

const taskSidebarMinWidth = 260;
const taskSidebarMaxWidth = 520;
const taskSidebarDefaultWidth = 320;

function clampTaskSidebarWidth(width: number): number {
  return Math.min(taskSidebarMaxWidth, Math.max(taskSidebarMinWidth, width));
}

function TasksPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
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
  const [draftResetVersion, setDraftResetVersion] = useState(0);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskSidebarWidth, setTaskSidebarWidth] = useState(taskSidebarDefaultWidth);
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
      queryClient.setQueryData<{ items: TaskSummary[] }>(['tasks'], (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
      }));
      selectTask(task.task_id);
      closeCreateDialog();
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

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  const trapDialogFocus = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') {
      return;
    }

    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
      )
    );
    if (focusable.length === 0) {
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }, []);

  const handleSplitterPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = taskSidebarWidth;

      const handlePointerMove = (moveEvent: PointerEvent) => {
        setTaskSidebarWidth(clampTaskSidebarWidth(startWidth + moveEvent.clientX - startX));
      };
      const handlePointerUp = () => {
        window.removeEventListener('pointermove', handlePointerMove);
        window.removeEventListener('pointerup', handlePointerUp);
      };

      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    },
    [taskSidebarWidth]
  );

  const handleSplitterKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
      return;
    }
    event.preventDefault();
    const delta = event.key === 'ArrowLeft' ? -16 : 16;
    setTaskSidebarWidth((width) => clampTaskSidebarWidth(width + delta));
  }, []);

  return (
    <div className="flex min-h-0 flex-1 bg-[var(--background)] p-4">
      <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-[var(--shadow-pane)]">
        <aside
          data-testid="task-sidebar"
          className="flex shrink-0 flex-col bg-[var(--sidebar)] p-3"
          style={{ width: taskSidebarWidth }}
        >
          <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--sidebar-border)] pb-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {t('pages.tasks.sidebarEyebrow')}
              </p>
              <h1 className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--sidebar-foreground)]">
                {t('pages.tasks.sidebarTitle')}
              </h1>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                {t('pages.tasks.sidebarCount', { count: tasks.length })}
              </p>
            </div>
            <button
              ref={createButtonRef}
              type="button"
              onClick={() => setCreateDialogOpen(true)}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--primary)] px-3 text-sm font-medium text-[var(--primary-foreground)] shadow-[var(--shadow-toolbar)] transition hover:opacity-90"
            >
              <Plus size={15} />
              {t('pages.tasks.newTask')}
            </button>
          </div>

          <TaskList
            tasks={tasks}
            selectedTaskId={effectiveSelectedTaskId}
            tasksError={tasksError}
            searchQuery={taskSearchQuery}
            onSearchQueryChange={setTaskSearchQuery}
            onSelectTask={selectTask}
          />
        </aside>

        <div
          role="separator"
          aria-label={t('pages.tasks.resizeTaskList')}
          aria-orientation="vertical"
          aria-valuemin={taskSidebarMinWidth}
          aria-valuemax={taskSidebarMaxWidth}
          aria-valuenow={taskSidebarWidth}
          tabIndex={0}
          onPointerDown={handleSplitterPointerDown}
          onKeyDown={handleSplitterKeyDown}
          className="group flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-[var(--card)] outline-none transition hover:bg-[var(--muted)] focus:bg-[var(--muted)]"
        >
          <span className="my-3 w-px rounded-full bg-[var(--border)] transition group-hover:bg-[var(--accent)] group-focus:bg-[var(--accent)]" />
        </div>

        <main className="flex min-w-0 flex-1 flex-col bg-[var(--background)] p-4">
          <TaskDetail
            selectedTask={selectedTask}
            detailError={detailError}
            outputItems={outputItems}
            outputError={outputError}
          />
        </main>
      </div>

      {isCreateDialogOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('pages.tasks.createTitle')}
            tabIndex={-1}
            onKeyDown={(event) => {
              trapDialogFocus(event);
              if (event.key === 'Escape') {
                closeCreateDialog();
              }
            }}
            className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-2xl"
          >
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
              onClose={closeCreateDialog}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default TasksPage;
