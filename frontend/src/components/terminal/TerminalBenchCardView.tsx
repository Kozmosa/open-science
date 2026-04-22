import TerminalSessionConsole from './TerminalSessionConsole';
import type { TerminalSessionStatus } from '../../types';
import { useT } from '../../i18n';

interface Props {
  sessionId: string | null;
  sessionName: string | null;
  attachmentId: string | null;
  status: TerminalSessionStatus;
  terminalWsUrl: string | null;
  detail: string | null;
  loadError: string | null;
  isLoading: boolean;
  isAttaching: boolean;
  isDetaching: boolean;
  isResetting: boolean;
  canAttach: boolean;
  canDetach: boolean;
  canReset: boolean;
  selectedEnvironmentSummary: string | null;
  onAttach: () => void;
  onDetach: () => void;
  onReset: () => void;
  onTerminalDisconnected: () => void;
}

function TerminalBenchCardView({
  sessionId,
  sessionName,
  attachmentId,
  status,
  terminalWsUrl,
  detail,
  loadError,
  isLoading,
  isAttaching,
  isDetaching,
  isResetting,
  canAttach,
  canDetach,
  canReset,
  selectedEnvironmentSummary,
  onAttach,
  onDetach,
  onReset,
  onTerminalDisconnected,
}: Props) {
  const t = useT();
  const statusLabel: Record<TerminalSessionStatus, string> = {
    idle: t('common.idle'),
    starting: t('common.starting'),
    running: t('common.running'),
    stopping: t('common.stopping'),
    failed: t('common.failed'),
  };
  const hasRuntimeError = loadError !== null || detail !== null;

  return (
    <section className="space-y-5 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">
              {t('components.terminalBench.eyebrow')}
            </p>
            <h2 className="mt-1 text-xl font-semibold text-gray-900">
              {t('components.terminalBench.title')}
            </h2>
          </div>
          <div className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-sm font-medium text-gray-700">
            {t('components.terminalBench.statusPrefix')} {statusLabel[status]}
          </div>
        </div>
        <p className="max-w-3xl text-sm text-gray-600">
          {t('components.terminalBench.description')}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onAttach}
          disabled={!canAttach}
          className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isAttaching ? t('components.terminalBench.attaching') : t('components.terminalBench.attach')}
        </button>
        <button
          type="button"
          onClick={onDetach}
          disabled={!canDetach}
          className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isDetaching ? t('components.terminalBench.detaching') : t('components.terminalBench.detach')}
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={!canReset}
          className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isResetting ? t('components.terminalBench.resetting') : t('components.terminalBench.resetSession')}
        </button>
      </div>

      <div className="space-y-2 rounded-2xl border border-gray-200 bg-gray-50 p-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-gray-700">
          <span className="font-medium text-gray-900">{t('components.terminalBench.sessionSource')}</span>
          <span>
            {t('components.terminalBench.loading')} {isLoading ? t('common.yes') : t('common.no')}
          </span>
          <span>
            {t('components.terminalBench.websocketUrl')} {terminalWsUrl ?? t('common.unavailable')}
          </span>
          <span>
            {t('components.terminalBench.environment')} {selectedEnvironmentSummary ?? t('common.notSelected')}
          </span>
          <span>
            {t('components.terminalBench.sessionName')} {sessionName ?? sessionId ?? t('common.unavailable')}
          </span>
          <span>
            {t('components.terminalBench.attachment')} {attachmentId ?? t('common.unavailable')}
          </span>
        </div>

        {loadError ? <p className="text-sm text-red-700">{t('components.terminalBench.loadError')} {loadError}</p> : null}
        {!selectedEnvironmentSummary ? (
          <p className="text-sm text-amber-700">
            {t('components.terminalBench.selectEnvironmentBeforeAttach')}
          </p>
        ) : null}
        {detail ? (
          <p className="text-sm text-gray-600">
            {t('common.detailLabel')} {detail}
          </p>
        ) : null}
        {!hasRuntimeError && !isLoading && status === 'idle' ? (
          <p className="text-sm text-gray-500">{t('components.terminalBench.noSessionYet')}</p>
        ) : null}
        {!hasRuntimeError && !isLoading && status === 'running' && terminalWsUrl === null ? (
          <p className="text-sm text-gray-500">{t('components.terminalBench.detachedNotice')}</p>
        ) : null}
      </div>

      <TerminalSessionConsole
        sessionId={sessionId}
        attachmentId={attachmentId}
        terminalWsUrl={terminalWsUrl}
        status={status}
        onDisconnected={onTerminalDisconnected}
      />
    </section>
  );
}

export default TerminalBenchCardView;
