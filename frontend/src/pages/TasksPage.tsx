import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  buildTaskStreamUrl,
  createTask,
  getTask,
  getTaskOutput,
  getTasks,
  getWorkspaces,
} from '../api';
import { useEnvironmentSelection } from '../components';
import { createEmptyEnvironmentTaskDefaults, useSettings } from '../settings';
import type {
  TaskCreateRequest,
  TaskOutputEvent,
  TaskStatus,
  TaskSummary,
  EnvironmentRecord,
  WorkspaceRecord,
} from '../types';

const statusLabel: Record<TaskStatus, string> = {
  queued: 'Queued',
  starting: 'Starting',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
};

function mergeOutputItems(current: TaskOutputEvent[], incoming: TaskOutputEvent[]): TaskOutputEvent[] {
  const bySeq = new Map<number, TaskOutputEvent>();
  for (const item of current) {
    bySeq.set(item.seq, item);
  }
  for (const item of incoming) {
    bySeq.set(item.seq, item);
  }
  return [...bySeq.values()].sort((left, right) => left.seq - right.seq);
}

interface TaskCreateFormProps {
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  selectedWorkspaceId: string;
  selectedEnvironmentId: string;
  selectedWorkspace: WorkspaceRecord | null;
  selectedEnvironment: EnvironmentRecord | null;
  draftDefaults: {
    title: string;
    task_input: string;
  };
  isSubmitting: boolean;
  createError: string | null;
  onSelectWorkspace: (workspaceId: string) => void;
  onSelectEnvironment: (environmentId: string) => void;
  onSubmit: (payload: TaskCreateRequest) => void;
}

function TaskCreateForm({
  workspaces,
  environments,
  selectedWorkspaceId,
  selectedEnvironmentId,
  selectedWorkspace,
  selectedEnvironment,
  draftDefaults,
  isSubmitting,
  createError,
  onSelectWorkspace,
  onSelectEnvironment,
  onSubmit,
}: TaskCreateFormProps) {
  const [draft, setDraft] = useState({
    title: draftDefaults.title,
    task_input: draftDefaults.task_input,
    task_profile: 'claude-code',
  });

  const canCreate =
    selectedWorkspace !== null &&
    selectedEnvironment !== null &&
    draft.task_input.trim().length > 0 &&
    !isSubmitting;

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!selectedWorkspace || !selectedEnvironment) {
          return;
        }

        onSubmit({
          workspace_id: selectedWorkspace.workspace_id,
          environment_id: selectedEnvironment.id,
          task_profile: draft.task_profile,
          task_input: draft.task_input.trim(),
          title: draft.title.trim() || undefined,
        });
      }}
    >
      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Workspace</span>
        <select
          aria-label="Workspace"
          value={selectedWorkspaceId}
          onChange={(event) => onSelectWorkspace(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {workspaces.map((workspace) => (
            <option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Environment</span>
        <select
          aria-label="Environment"
          value={selectedEnvironmentId}
          onChange={(event) => onSelectEnvironment(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {environments.map((environment) => (
            <option key={environment.id} value={environment.id}>
              {environment.alias} · {environment.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Task profile</span>
        <select
          aria-label="Task profile"
          value={draft.task_profile}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_profile: event.target.value }))
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          <option value="claude-code">claude-code</option>
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Title</span>
        <input
          aria-label="Title"
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder="Optional"
        />
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Task input</span>
        <textarea
          aria-label="Task input"
          value={draft.task_input}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_input: event.target.value }))
          }
          className="min-h-40 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder="Implement Task Harness v1 according to the current repository plan."
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
          onClick={() =>
            setDraft({
              title: draftDefaults.title,
              task_input: draftDefaults.task_input,
              task_profile: 'claude-code',
            })
          }
        >
          Reset draft
        </button>

        <button
          type="submit"
          disabled={!canCreate}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isSubmitting ? 'Creating…' : 'Create task'}
        </button>
      </div>

      {selectedWorkspace ? (
        <p className="rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
          Default workdir: <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedWorkspace.default_workdir ?? 'n/a'}</code>
        </p>
      ) : null}
      {createError ? <p className="text-sm text-[#ff3b30]">{createError}</p> : null}
    </form>
  );
}

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
  const [outputItems, setOutputItems] = useState<TaskOutputEvent[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const nextSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);

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

  useEffect(() => {
    if (effectiveSelectedTaskId === null) {
      nextSeqRef.current = 0;
      return undefined;
    }
    let active = true;

    const closeStream = (): void => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const appendOutput = (items: TaskOutputEvent[]): void => {
      setOutputItems((current) => mergeOutputItems(current, items));
      if (items.length > 0) {
        nextSeqRef.current = items[items.length - 1]?.seq ?? nextSeqRef.current;
      }
    };

    const refillGap = async (): Promise<void> => {
      try {
        const page = await getTaskOutput(effectiveSelectedTaskId, nextSeqRef.current);
        if (!active) {
          return;
        }
        appendOutput(page.items);
        nextSeqRef.current = page.next_seq;
      } catch (error) {
        if (active) {
          setOutputError(error instanceof Error ? error.message : 'Unable to replay task output');
        }
      }
    };

    const openStream = (): void => {
      closeStream();
      const source = new EventSource(buildTaskStreamUrl(effectiveSelectedTaskId, nextSeqRef.current));
      eventSourceRef.current = source;
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          const item = JSON.parse(event.data) as TaskOutputEvent;
          if (item.seq > nextSeqRef.current + 1) {
            void refillGap();
          }
          if (item.seq > nextSeqRef.current) {
            appendOutput([item]);
          }
          if (item.kind === 'lifecycle') {
            void queryClient.invalidateQueries({ queryKey: ['tasks'] });
            void queryClient.invalidateQueries({ queryKey: ['task', effectiveSelectedTaskId] });
          }
        } catch (error) {
          setOutputError(error instanceof Error ? error.message : 'Unable to parse task output');
        }
      };
      source.onerror = () => {
        source.close();
        if (!active) {
          return;
        }
        void refillGap().finally(() => {
          if (!active) {
            return;
          }
          reconnectTimerRef.current = window.setTimeout(openStream, 1000);
        });
      };
    };

    void (async () => {
      try {
        setOutputError(null);
        const page = await getTaskOutput(effectiveSelectedTaskId, 0);
        if (!active) {
          return;
        }
        setOutputItems(page.items);
        nextSeqRef.current = page.next_seq;
        openStream();
      } catch (error) {
        if (active) {
          setOutputError(error instanceof Error ? error.message : 'Unable to load task output');
        }
      }
    })();

    return () => {
      active = false;
      closeStream();
    };
  }, [effectiveSelectedTaskId, queryClient]);

  const effectiveWorkspaceId = selectedWorkspaceId || workspaces[0]?.workspace_id || '';
  const effectiveEnvironmentId = environmentSelection.selectedEnvironmentId || environments[0]?.id || '';
  const selectedWorkspace =
    workspaces.find((workspace) => workspace.workspace_id === effectiveWorkspaceId) ?? null;
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const draftDefaults = useMemo(() => {
    const environmentDefaults =
      (environmentSelection.selectedEnvironmentId
        ? settings.projectDefaults.default.environmentDefaults[environmentSelection.selectedEnvironmentId]
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

          <section className="space-y-4">
            <div className="space-y-1">
              <h2
                className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
                style={{ fontFamily: 'var(--font-display)' }}
              >
                Task list
              </h2>
              <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
                All harness-managed tasks are listed below.
              </p>
            </div>
            {tasksError ? <p className="text-sm text-[#ff3b30]">{tasksError}</p> : null}
            <div className="space-y-3">
              {tasks.length === 0 ? (
                <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                  No tasks have been created yet.
                </div>
              ) : (
                tasks.map((task) => (
                  <button
                    key={task.task_id}
                    type="button"
                    onClick={() => setSelectedTaskId(task.task_id)}
                    className={[
                      'flex w-full flex-col gap-2 rounded-lg px-4 py-4 text-left transition',
                      effectiveSelectedTaskId === task.task_id
                        ? 'bg-[var(--apple-blue)]/10'
                        : 'bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)]',
                    ].join(' ')}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <span className="text-sm font-semibold text-[var(--text)]">{task.title}</span>
                      <span className="rounded-full bg-[var(--bg)] px-3 py-1 text-xs font-medium text-[var(--text)] border border-[var(--border)]">
                        {statusLabel[task.status]}
                      </span>
                    </div>
                    <p className="text-xs tracking-[-0.12px] text-[var(--text-secondary)]">
                      {task.workspace_summary.label} · {task.environment_summary.alias}
                    </p>
                    <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                      Updated {task.updated_at}
                    </p>
                  </button>
                ))
              )}
            </div>
          </section>
        </section>

        <section className="space-y-6 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
          <div className="space-y-1">
            <h2
              className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              Task detail
            </h2>
            <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
              Detail combines binding snapshot, prompt layers, runtime payload, output replay, and
              result summary.
            </p>
          </div>

          {detailError ? <p className="text-sm text-[#ff3b30]">{detailError}</p> : null}
          {selectedTask ? (
            <div className="space-y-6">
              <section className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Summary
                </h3>
                <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text)]">Status:</span>{' '}
                  {statusLabel[selectedTask.status]}
                </p>
                <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text)]">Workspace:</span>{' '}
                  {selectedTask.workspace_summary.label}
                </p>
                <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text)]">Environment:</span>{' '}
                  {selectedTask.environment_summary.alias} · {selectedTask.environment_summary.display_name}
                </p>
                <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                  <span className="font-medium text-[var(--text)]">Latest seq:</span>{' '}
                  {selectedTask.latest_output_seq}
                </p>
                {selectedTask.error_summary ? (
                  <p className="text-sm text-[#ff3b30]">{selectedTask.error_summary}</p>
                ) : null}
              </section>

              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Binding
                </h3>
                {selectedTask.binding ? (
                  <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                    <p>
                      <span className="font-medium text-[var(--text)]">Resolved workdir:</span>{' '}
                      <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.binding.resolved_workdir}</code>
                    </p>
                    <p>
                      <span className="font-medium text-[var(--text)]">Snapshot:</span>{' '}
                      <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.binding.snapshot_path}</code>
                    </p>
                  </div>
                ) : (
                  <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                    Binding snapshot is not available yet.
                  </p>
                )}
              </section>

              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Prompt
                </h3>
                {selectedTask.prompt ? (
                  <div className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
                    {selectedTask.prompt.layers.map((layer) => (
                      <div key={layer.name} className="space-y-1">
                        <p className="text-sm font-medium text-[var(--text)]">
                          {layer.label}{' '}
                          <span className="text-xs text-[var(--text-tertiary)]">
                            ({layer.char_count} chars)
                          </span>
                        </p>
                        <pre className="overflow-x-auto rounded-lg bg-[var(--bg)] p-3 text-xs tracking-[-0.12px] text-[var(--text-secondary)]">
                          {layer.content}
                        </pre>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                    Prompt manifest is not available yet.
                  </p>
                )}
              </section>

              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Runtime
                </h3>
                {selectedTask.runtime ? (
                  <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                    <p>
                      <span className="font-medium text-[var(--text)]">Runner:</span>{' '}
                      {selectedTask.runtime.runner_kind ?? 'n/a'}
                    </p>
                    <p>
                      <span className="font-medium text-[var(--text)]">Working directory:</span>{' '}
                      <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.runtime.working_directory ?? 'n/a'}</code>
                    </p>
                    <p>
                      <span className="font-medium text-[var(--text)]">Command:</span>{' '}
                      <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedTask.runtime.command.join(' ') || 'pending'}</code>
                    </p>
                  </div>
                ) : (
                  <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                    Runtime payload is not available yet.
                  </p>
                )}
              </section>

              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Output
                </h3>
                {outputError ? <p className="text-sm text-[#ff3b30]">{outputError}</p> : null}
                <div className="max-h-[26rem] space-y-2 overflow-auto rounded-lg border border-[var(--border)] bg-[#0b1020] p-4 text-xs text-gray-100">
                  {outputItems.length === 0 ? (
                    <p className="text-gray-400">No output has been recorded yet.</p>
                  ) : (
                    outputItems.map((item) => (
                      <div key={item.seq} className="space-y-1">
                        <p className="text-[11px] uppercase tracking-[0.08em] text-gray-400">
                          #{item.seq} · {item.kind}
                        </p>
                        <pre className="whitespace-pre-wrap break-words">{item.content}</pre>
                      </div>
                    ))
                  )}
                </div>
              </section>

              <section className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                  Result
                </h3>
                <div className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
                  <p>
                    <span className="font-medium text-[var(--text)]">Exit code:</span>{' '}
                    {selectedTask.result.exit_code ?? 'n/a'}
                  </p>
                  <p>
                    <span className="font-medium text-[var(--text)]">Failure category:</span>{' '}
                    {selectedTask.result.failure_category ?? 'n/a'}
                  </p>
                  <p>
                    <span className="font-medium text-[var(--text)]">Completed at:</span>{' '}
                    {selectedTask.result.completed_at ?? 'n/a'}
                  </p>
                </div>
              </section>
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              Select a task from the list to inspect its persisted state.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default TasksPage;
