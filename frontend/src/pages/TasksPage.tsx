import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  cancelTask,
  createTask,
  getTask,
  getTasks,
  getTaskTerminal,
  releaseTaskTerminal,
} from '../api';
import { getAppUserId } from '../api/appUser';
import { EnvironmentSelectorPanel, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import type { TaskCreateRequest, TaskListResponse, TaskRecord, TaskTerminalBinding, TaskStatus } from '../types';

const statusLabelKey: Record<TaskStatus, string> = {
  pending: 'pages.tasks.status.pending',
  running: 'common.running',
  completed: 'pages.tasks.status.completed',
  failed: 'common.failed',
  cancelled: 'pages.tasks.status.cancelled',
};

function TasksPage() {
  const t = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const environmentSelection = useEnvironmentSelection();
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const selectedEnvironmentId = selectedEnvironment?.id ?? null;
  const currentUserId = getAppUserId();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    title: '',
    command: '',
    workingDirectory: '',
  });

  const tasksQuery = useQuery({
    queryKey: ['tasks', selectedEnvironmentId],
    queryFn: () => {
      if (!selectedEnvironmentId) {
        return Promise.resolve<TaskListResponse>({ items: [] });
      }
      return getTasks(selectedEnvironmentId);
    },
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const effectiveSelectedTaskId = useMemo(() => {
    if (!selectedEnvironmentId) {
      return null;
    }
    if (selectedTaskId && tasks.some((task) => task.task_id === selectedTaskId)) {
      return selectedTaskId;
    }
    return tasks[0]?.task_id ?? null;
  }, [selectedEnvironmentId, selectedTaskId, tasks]);

  const selectedTaskQuery = useQuery({
    queryKey: ['task', effectiveSelectedTaskId],
    queryFn: () => getTask(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
  });
  const selectedTerminalQuery = useQuery({
    queryKey: ['task-terminal', effectiveSelectedTaskId],
    queryFn: () => getTaskTerminal(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
  });

  const selectedTask =
    selectedTaskQuery.data ??
    tasks.find((task) => task.task_id === effectiveSelectedTaskId) ??
    null;
  const selectedTerminal = selectedTerminalQuery.data ?? selectedTask?.terminal ?? null;

  function upsertTask(task: TaskRecord): void {
    queryClient.setQueryData<TaskRecord>(['task', task.task_id], task);
    if (task.terminal) {
      queryClient.setQueryData<TaskTerminalBinding>(['task-terminal', task.task_id], task.terminal);
    }
    queryClient.setQueryData<TaskListResponse>(['tasks', task.environment_id], (current) => {
      const items = current?.items ?? [];
      const next = [task, ...items.filter((item) => item.task_id !== task.task_id)];
      next.sort((left, right) => right.created_at.localeCompare(left.created_at));
      return { items: next };
    });
  }

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreateRequest) => createTask(payload),
    onSuccess: (task) => {
      upsertTask(task);
      setSelectedTaskId(task.task_id);
      setDraft({ title: '', command: '', workingDirectory: '' });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelTask(taskId),
    onSuccess: (task) => {
      upsertTask(task);
      void queryClient.invalidateQueries({ queryKey: ['tasks', task.environment_id] });
      void queryClient.invalidateQueries({ queryKey: ['task-terminal', task.task_id] });
    },
  });

  const releaseMutation = useMutation({
    mutationFn: (taskId: string) => releaseTaskTerminal(taskId),
    onSuccess: (_attachment, taskId) => {
      void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      void queryClient.invalidateQueries({ queryKey: ['task-terminal', taskId] });
      if (selectedEnvironmentId) {
        void queryClient.invalidateQueries({ queryKey: ['tasks', selectedEnvironmentId] });
      }
    },
  });

  const selectedEnvironmentSummary = useMemo(() => {
    if (!selectedEnvironment) {
      return null;
    }
    return `${selectedEnvironment.alias} · ${selectedEnvironment.display_name}`;
  }, [selectedEnvironment]);

  const createError = createMutation.error instanceof Error ? createMutation.error.message : null;
  const tasksError = tasksQuery.error instanceof Error ? tasksQuery.error.message : null;
  const detailError = selectedTaskQuery.error instanceof Error ? selectedTaskQuery.error.message : null;
  const terminalError =
    selectedTerminalQuery.error instanceof Error
      ? selectedTerminalQuery.error.message
      : releaseMutation.error instanceof Error
        ? releaseMutation.error.message
        : cancelMutation.error instanceof Error
          ? cancelMutation.error.message
          : null;

  const canCreate =
    selectedEnvironmentId !== null &&
    draft.title.trim().length > 0 &&
    draft.command.trim().length > 0 &&
    !createMutation.isPending;
  const canCancel =
    effectiveSelectedTaskId !== null &&
    selectedTask !== null &&
    !cancelMutation.isPending &&
    !['completed', 'failed', 'cancelled'].includes(selectedTask.status);
  const canRelease =
    effectiveSelectedTaskId !== null &&
    selectedTerminal !== null &&
    selectedTerminal.binding_status === 'taken_over' &&
    selectedTerminal.ownership_user_id === currentUserId &&
    !releaseMutation.isPending;

  function navigateToTerminal(intent: 'open' | 'takeover'): void {
    if (!selectedTask) {
      return;
    }
    const params = new URLSearchParams({
      environment_id: selectedTask.environment_id,
      task_id: selectedTask.task_id,
      intent,
    });
    navigate(`/terminal?${params.toString()}`);
  }

  function terminalStatusLabel(binding: TaskTerminalBinding | null): string {
    if (!binding) {
      return t('pages.terminal.task.pending');
    }
    if (binding.binding_status === 'taken_over') {
      return t('pages.terminal.task.takenOver');
    }
    if (binding.binding_status === 'running_observe') {
      return t('pages.terminal.task.observeOnly');
    }
    if (binding.binding_status === 'completed') {
      return t('pages.tasks.status.completed');
    }
    if (binding.binding_status === 'archived') {
      return t('pages.terminal.task.archived');
    }
    if (binding.binding_status === 'failed') {
      return t('common.failed');
    }
    return t('pages.terminal.task.pending');
  }

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="mb-8 space-y-3">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
          {t('pages.tasks.eyebrow')}
        </p>
        <h1 className="text-3xl font-semibold text-gray-900">{t('pages.tasks.title')}</h1>
        <p className="max-w-3xl text-sm text-gray-600 sm:text-base">{t('pages.tasks.description')}</p>
      </section>

      <div className="space-y-6">
        <EnvironmentSelectorPanel {...environmentSelection} />

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
          <section className="space-y-6 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="space-y-1">
              <h2 className="text-lg font-medium text-gray-900">{t('pages.tasks.createTitle')}</h2>
              <p className="text-sm text-gray-600">{t('pages.tasks.createDescription')}</p>
            </div>

            <form
              className="space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (!selectedEnvironmentId) {
                  return;
                }
                createMutation.mutate({
                  environment_id: selectedEnvironmentId,
                  title: draft.title.trim(),
                  command: draft.command.trim(),
                  working_directory: draft.workingDirectory.trim() || undefined,
                });
              }}
            >
              <label className="block space-y-2">
                <span className="text-sm font-medium text-gray-700">{t('pages.tasks.titleLabel')}</span>
                <input
                  aria-label={t('pages.tasks.titleLabel')}
                  value={draft.title}
                  onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                  className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15"
                  placeholder="Train Task"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-gray-700">{t('pages.tasks.commandLabel')}</span>
                <textarea
                  aria-label={t('pages.tasks.commandLabel')}
                  value={draft.command}
                  onChange={(event) => setDraft((current) => ({ ...current, command: event.target.value }))}
                  className="min-h-28 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15"
                  placeholder="python train.py --epochs 3"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-sm font-medium text-gray-700">
                  {t('pages.tasks.workingDirectoryLabel')}
                </span>
                <input
                  aria-label={t('pages.tasks.workingDirectoryLabel')}
                  value={draft.workingDirectory}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, workingDirectory: event.target.value }))
                  }
                  className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15"
                  placeholder="/workspace/project"
                />
              </label>

              {createError ? <p className="text-sm text-red-700">{createError}</p> : null}
              {!selectedEnvironmentSummary ? (
                <p className="text-sm text-amber-700">{t('pages.tasks.selectEnvironmentPrompt')}</p>
              ) : null}

              <button
                type="submit"
                disabled={!canCreate}
                className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {createMutation.isPending ? t('pages.tasks.creatingAction') : t('pages.tasks.createAction')}
              </button>
            </form>
          </section>

          <section className="space-y-6">
            <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="space-y-1">
                <h2 className="text-lg font-medium text-gray-900">{t('pages.tasks.listTitle')}</h2>
                <p className="text-sm text-gray-600">{t('pages.tasks.listDescription')}</p>
              </div>

              {tasksError ? <p className="text-sm text-red-700">{tasksError}</p> : null}

              <div className="space-y-3">
                {tasks.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500">
                    {t('pages.tasks.empty')}
                  </div>
                ) : (
                  tasks.map((task) => (
                    <button
                      key={task.task_id}
                      type="button"
                      onClick={() => setSelectedTaskId(task.task_id)}
                      className={[
                        'flex w-full flex-col gap-2 rounded-2xl border px-4 py-4 text-left transition',
                        effectiveSelectedTaskId === task.task_id
                          ? 'border-[var(--accent)]/25 bg-[var(--accent)]/10'
                          : 'border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-white',
                      ].join(' ')}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="text-sm font-semibold text-gray-900">{task.title}</span>
                        <span className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700">
                          {t(statusLabelKey[task.status] as never)}
                        </span>
                      </div>
                      <p className="text-xs text-gray-600">
                        {t('pages.tasks.windowLabel')} {task.terminal?.window_name ?? 'n/a'}
                      </p>
                      <p className="text-xs text-gray-600">
                        {t('pages.tasks.bindingStatusLabel')} {terminalStatusLabel(task.terminal)}
                      </p>
                      <p className="text-xs text-gray-500">
                        {t('pages.tasks.updatedAtLabel')} {task.updated_at}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </section>

            <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="space-y-1">
                <h2 className="text-lg font-medium text-gray-900">{t('pages.tasks.detailTitle')}</h2>
                <p className="text-sm text-gray-600">{t('pages.tasks.detailDescription')}</p>
              </div>

              {selectedTask ? (
                <>
                  <div className="space-y-2 rounded-2xl border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                    <p>
                      <span className="font-medium text-gray-900">{t('pages.tasks.statusLabel')}</span>{' '}
                      {t(statusLabelKey[selectedTask.status] as never)}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">
                        {t('pages.tasks.bindingStatusLabel')}
                      </span>{' '}
                      {terminalStatusLabel(selectedTerminal)}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">
                        {t('pages.tasks.environmentLabel')}
                      </span>{' '}
                      {selectedTask.environment_alias ?? selectedTask.environment_id}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">{t('pages.tasks.windowLabel')}</span>{' '}
                      {selectedTerminal?.window_name ?? 'n/a'}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">{t('pages.tasks.ownerLabel')}</span>{' '}
                      {selectedTerminal?.ownership_user_id ?? t('pages.tasks.noOwner')}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">
                        {t('pages.tasks.lastOutputLabel')}
                      </span>{' '}
                      {selectedTerminal?.last_output_at ?? t('common.unavailable')}
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">{t('pages.tasks.commandLabel')}</span>{' '}
                      <code className="rounded bg-white px-2 py-1">{selectedTask.command}</code>
                    </p>
                    <p>
                      <span className="font-medium text-gray-900">
                        {t('pages.tasks.workingDirectoryLabel')}
                      </span>{' '}
                      <code className="rounded bg-white px-2 py-1">{selectedTask.working_directory}</code>
                    </p>
                  </div>

                  {detailError ? <p className="text-sm text-red-700">{detailError}</p> : null}
                  {terminalError ? <p className="text-sm text-red-700">{terminalError}</p> : null}

                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => navigateToTerminal('open')}
                      disabled={effectiveSelectedTaskId === null}
                      className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {t('pages.tasks.openTerminal')}
                    </button>
                    <button
                      type="button"
                      onClick={() => navigateToTerminal('takeover')}
                      disabled={effectiveSelectedTaskId === null}
                      className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {t('pages.tasks.takeover')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (effectiveSelectedTaskId) {
                          releaseMutation.mutate(effectiveSelectedTaskId);
                        }
                      }}
                      disabled={!canRelease}
                      className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {releaseMutation.isPending
                        ? t('pages.tasks.releasingAction')
                        : t('pages.tasks.release')}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (effectiveSelectedTaskId) {
                          cancelMutation.mutate(effectiveSelectedTaskId);
                        }
                      }}
                      disabled={!canCancel}
                      className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {cancelMutation.isPending
                        ? t('pages.tasks.cancellingAction')
                        : t('pages.tasks.cancelTask')}
                    </button>
                  </div>
                </>
              ) : (
                <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500">
                  {t('pages.tasks.selectTaskPrompt')}
                </div>
              )}
            </section>
          </section>
        </div>
      </div>
    </div>
  );
}

export default TasksPage;
