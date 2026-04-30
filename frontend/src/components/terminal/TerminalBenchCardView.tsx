import { Button, SectionCard, SectionHeader, StatusDot } from '../ui';
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

  const statusMap: Record<TerminalSessionStatus, 'success' | 'error' | 'warning' | 'idle'> = {
    idle: 'idle',
    starting: 'warning',
    running: 'success',
    stopping: 'warning',
    failed: 'error',
  };

  return (
    <SectionCard>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SectionHeader
            eyebrow={t('components.terminalBench.eyebrow')}
            title={t('components.terminalBench.title')}
            description={t('components.terminalBench.description')}
            size="md"
          />
          <div className="inline-flex items-center gap-2 rounded-full bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm font-medium text-[var(--text)]">
            <StatusDot status={statusMap[status]} />
            {t('components.terminalBench.statusPrefix')} {statusLabel[status]}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          onClick={onAttach}
          disabled={!canAttach}
          isLoading={isAttaching}
        >
          {isAttaching ? t('components.terminalBench.attaching') : t('components.terminalBench.attach')}
        </Button>
        <Button
          variant="secondary"
          onClick={onDetach}
          disabled={!canDetach}
          isLoading={isDetaching}
        >
          {isDetaching ? t('components.terminalBench.detaching') : t('components.terminalBench.detach')}
        </Button>
        <Button
          variant="secondary"
          onClick={onReset}
          disabled={!canReset}
          isLoading={isResetting}
        >
          {isResetting ? t('components.terminalBench.resetting') : t('components.terminalBench.resetSession')}
        </Button>
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

      <SectionCard
        collapsible
        defaultExpanded={false}
        header={
          <div className="text-sm font-medium text-[var(--text)]">
            终端控制台
          </div>
        }
      >
        <TerminalSessionConsole
          sessionId={sessionId}
          attachmentId={attachmentId}
          terminalWsUrl={terminalWsUrl}
          status={status}
          onDisconnected={onTerminalDisconnected}
        />
      </SectionCard>
    </SectionCard>
  );
}

export default TerminalBenchCardView;
