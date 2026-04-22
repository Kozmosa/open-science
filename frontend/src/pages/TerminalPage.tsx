import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getTask, getTaskTerminal, openTaskTerminal, releaseTaskTerminal, takeoverTaskTerminal } from '../api';
import { getAppUserId } from '../api/appUser';
import { TerminalSessionConsole } from '../components';
import { useT } from '../i18n';
import type { TaskRecord, TaskTerminalBinding, TerminalAttachment } from '../types';
import DashboardPage from './DashboardPage';

type TaskAttachIntent = 'open' | 'takeover';

function TerminalPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const environmentId = searchParams.get('environment_id');
  const intent: TaskAttachIntent = searchParams.get('intent') === 'takeover' ? 'takeover' : 'open';
  const currentUserId = getAppUserId();
  const [attachmentState, setAttachmentState] = useState<{
    taskId: string;
    attachment: TerminalAttachment;
  } | null>(null);
  const attachKeyRef = useRef<string | null>(null);

  const taskQuery = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => getTask(taskId ?? ''),
    enabled: taskId !== null,
  });
  const terminalQuery = useQuery({
    queryKey: ['task-terminal', taskId],
    queryFn: () => getTaskTerminal(taskId ?? ''),
    enabled: taskId !== null,
  });

  const attachMutation = useMutation({
    mutationFn: (payload: { taskId: string; intent: TaskAttachIntent }) =>
      payload.intent === 'takeover'
        ? takeoverTaskTerminal(payload.taskId)
        : openTaskTerminal(payload.taskId),
    onSuccess: (nextAttachment, payload) => {
      setAttachmentState({ taskId: payload.taskId, attachment: nextAttachment });
      void queryClient.invalidateQueries({ queryKey: ['task', payload.taskId] });
      void queryClient.invalidateQueries({ queryKey: ['task-terminal', payload.taskId] });
    },
    onError: () => {
      attachKeyRef.current = null;
    },
  });

  const releaseMutation = useMutation({
    mutationFn: (nextTaskId: string) => releaseTaskTerminal(nextTaskId),
    onSuccess: (nextAttachment, releasedTaskId) => {
      setAttachmentState({ taskId: releasedTaskId, attachment: nextAttachment });
      attachKeyRef.current = `${releasedTaskId}:open`;
      void queryClient.invalidateQueries({ queryKey: ['task', releasedTaskId] });
      void queryClient.invalidateQueries({ queryKey: ['task-terminal', releasedTaskId] });
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('intent', 'open');
      setSearchParams(nextParams, { replace: true });
    },
  });

  const task: TaskRecord | null = taskQuery.data ?? null;
  const terminalBinding: TaskTerminalBinding | null = terminalQuery.data ?? task?.terminal ?? null;

  useEffect(() => {
    if (taskId === null) {
      attachKeyRef.current = null;
      return;
    }
    if (taskQuery.isLoading || terminalQuery.isLoading || attachMutation.isPending) {
      return;
    }
    if (terminalBinding?.binding_status === 'archived') {
      attachKeyRef.current = null;
      return;
    }
    const attachKey = `${taskId}:${intent}`;
    if (attachKeyRef.current === attachKey) {
      return;
    }
    attachKeyRef.current = attachKey;
    attachMutation.mutate({ taskId, intent });
  }, [attachMutation, intent, taskId, taskQuery.isLoading, terminalBinding?.binding_status, terminalQuery.isLoading]);
  const effectiveAttachment =
    attachmentState?.taskId === taskId && terminalBinding?.binding_status !== 'archived'
      ? attachmentState.attachment
      : null;
  const effectiveMode = effectiveAttachment?.mode ?? terminalBinding?.mode ?? 'observe';
  const effectiveReadonly = effectiveAttachment?.readonly ?? terminalBinding?.readonly ?? true;
  const effectiveWindowName = effectiveAttachment?.window_name ?? terminalBinding?.window_name ?? 'n/a';
  const isTakenOver = terminalBinding?.binding_status === 'taken_over';
  const canRelease =
    terminalBinding?.ownership_user_id === currentUserId &&
    terminalBinding.binding_status === 'taken_over' &&
    !releaseMutation.isPending;
  const runtimeError =
    taskQuery.error instanceof Error
      ? taskQuery.error.message
      : terminalQuery.error instanceof Error
        ? terminalQuery.error.message
        : attachMutation.error instanceof Error
          ? attachMutation.error.message
          : releaseMutation.error instanceof Error
            ? releaseMutation.error.message
            : null;

  const bindingStatusLabel = useMemo(() => {
    const bindingStatus = terminalBinding?.binding_status;
    if (bindingStatus === 'taken_over') {
      return t('pages.terminal.task.takenOver');
    }
    if (bindingStatus === 'running_observe') {
      return t('pages.terminal.task.observeOnly');
    }
    if (bindingStatus === 'completed') {
      return t('pages.tasks.status.completed');
    }
    if (bindingStatus === 'failed') {
      return t('common.failed');
    }
    if (bindingStatus === 'archived') {
      return t('pages.terminal.task.archived');
    }
    return t('pages.terminal.task.pending');
  }, [t, terminalBinding?.binding_status]);

  if (taskId === null) {
    return <DashboardPage />;
  }

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
          {t('pages.terminal.eyebrow')}
        </p>
        <h1 className="text-3xl font-semibold text-gray-900">{t('pages.terminal.title')}</h1>
        <p className="max-w-3xl text-sm text-gray-600 sm:text-base">
          {t('pages.terminal.description')}
        </p>
      </section>

      <section className="mt-6 space-y-5 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <span className="rounded-full border border-[var(--accent)]/20 bg-[var(--accent)]/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
                {bindingStatusLabel}
              </span>
              <span className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-700">
                {effectiveMode === 'observe'
                  ? t('pages.terminal.task.observeOnly')
                  : t('pages.terminal.task.takenOver')}
              </span>
            </div>
            <h2 className="text-xl font-semibold text-gray-900">{task?.title ?? taskId}</h2>
            <p className="text-sm text-gray-600">
              {t('pages.terminal.task.windowLabel')} {effectiveWindowName}
            </p>
            <p className="text-sm text-gray-600">
              {t('pages.terminal.task.ownerLabel')}{' '}
              {terminalBinding?.ownership_user_id ?? t('pages.terminal.task.noOwner')}
            </p>
            <p className="text-sm text-gray-600">
              {t('pages.terminal.task.environmentLabel')}{' '}
              {task?.environment_alias ?? environmentId ?? t('common.unavailable')}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              to={task?.environment_id ? `/tasks?environment_id=${encodeURIComponent(task.environment_id)}` : '/tasks'}
              className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
            >
              {t('pages.terminal.backToTasks')}
            </Link>
            <button
              type="button"
              onClick={() => {
                if (taskId) {
                  releaseMutation.mutate(taskId);
                }
              }}
              disabled={!canRelease}
              className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {releaseMutation.isPending
                ? t('pages.tasks.releasingAction')
                : t('pages.tasks.release')}
            </button>
          </div>
        </div>

        {runtimeError ? <p className="text-sm text-red-700">{runtimeError}</p> : null}
        {task?.detail ? (
          <p className="text-sm text-gray-600">
            {t('common.detailLabel')} {task.detail}
          </p>
        ) : null}
        {terminalBinding?.last_output_at ? (
          <p className="text-sm text-gray-600">
            {t('pages.terminal.task.lastOutputLabel')} {terminalBinding.last_output_at}
          </p>
        ) : null}
        {isTakenOver && terminalBinding?.ownership_user_id !== currentUserId ? (
          <p className="text-sm text-amber-700">{t('pages.terminal.task.otherOwner')}</p>
        ) : null}

        <TerminalSessionConsole
          sessionId={effectiveAttachment?.session_name ?? terminalBinding?.agent_session_name ?? null}
          attachmentId={effectiveAttachment?.attachment_id ?? null}
          terminalWsUrl={effectiveAttachment?.terminal_ws_url ?? null}
          status={task?.status === 'running' ? 'running' : 'idle'}
          readonly={effectiveReadonly}
          mode={effectiveMode}
          placeholderText={t('pages.terminal.task.placeholder')}
          onDisconnected={() => {
            if (taskId) {
              setAttachmentState(null);
              attachKeyRef.current = null;
              void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
              void queryClient.invalidateQueries({ queryKey: ['task-terminal', taskId] });
            }
          }}
        />
      </section>
    </div>
  );
}

export default TerminalPage;
