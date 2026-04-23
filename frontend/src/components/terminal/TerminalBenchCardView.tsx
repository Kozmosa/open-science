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

  const statusColor =
    status === 'running'
      ? 'bg-[#34c759]'
      : status === 'failed'
        ? 'bg-[#ff3b30]'
        : status === 'starting' || status === 'stopping'
          ? 'bg-[#ff9500]'
          : 'bg-[var(--text-tertiary)]';

  return (
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
              {t('components.terminalBench.eyebrow')}
            </p>
            <h2
              className="mt-1 text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              {t('components.terminalBench.title')}
            </h2>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm font-medium text-[var(--text)]">
            <span className={`h-2 w-2 rounded-full ${statusColor}`} />
            {t('components.terminalBench.statusPrefix')} {statusLabel[status]}
          </div>
        </div>
        <p className="max-w-3xl text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('components.terminalBench.description')}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onAttach}
          disabled={!canAttach}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isAttaching ? t('components.terminalBench.attaching') : t('components.terminalBench.attach')}
        </button>
        <button
          type="button"
          onClick={onDetach}
          disabled={!canDetach}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isDetaching ? t('components.terminalBench.detaching') : t('components.terminalBench.detach')}
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={!canReset}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isResetting ? t('components.terminalBench.resetting') : t('components.terminalBench.resetSession')}
        </button>
      </div>

      <div className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
          <span className="font-medium text-[var(--text)]">
            {t('components.terminalBench.sessionSource')}
          </span>
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

        {loadError ? (
          <p className="text-sm text-[#ff3b30]">
            {t('components.terminalBench.loadError')} {loadError}
          </p>
        ) : null}
        {!selectedEnvironmentSummary ? (
          <p className="text-sm text-[#ff9500]">
            {t('components.terminalBench.selectEnvironmentBeforeAttach')}
          </p>
        ) : null}
        {detail ? (
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('common.detailLabel')} {detail}
          </p>
        ) : null}
        {!hasRuntimeError && !isLoading && status === 'idle' ? (
          <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
            {t('components.terminalBench.noSessionYet')}
          </p>
        ) : null}
        {!hasRuntimeError && !isLoading && status === 'running' && terminalWsUrl === null ? (
          <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
            {t('components.terminalBench.detachedNotice')}
          </p>
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
