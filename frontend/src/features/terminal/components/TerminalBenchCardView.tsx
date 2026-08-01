import { useEffect, useRef, useState } from 'react';
import { Button, Dialog, SectionCard, SectionHeader, StatusDot, useToast } from '@design-system';
import TerminalSessionConsole from './TerminalSessionConsole';
import type { TerminalSessionStatus } from '@/shared/types';
import { useT } from '@/shared/i18n';

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
  consoleExpanded: boolean;
  onToggleConsole: () => void;
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
  consoleExpanded,
  onToggleConsole,
}: Props) {
  const t = useT();
  const { showToast } = useToast();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const previousDetailRef = useRef<string | null>(null);
  const statusLabel: Record<TerminalSessionStatus, string> = {
    idle: t('common.idle'),
    starting: t('common.starting'),
    running: t('common.running'),
    stopping: t('common.stopping'),
    failed: t('common.failed'),
  };
  const hasRuntimeError = loadError !== null || detail !== null;

  useEffect(() => {
    if (detail !== null && detail !== previousDetailRef.current) {
      showToast(`${t('components.terminalBench.detailUpdated')} ${detail}`, 'warning');
    }
    previousDetailRef.current = detail;
  }, [detail, showToast, t]);

  const statusMap: Record<TerminalSessionStatus, 'success' | 'error' | 'warning' | 'idle'> = {
    idle: 'idle',
    starting: 'warning',
    running: 'success',
    stopping: 'warning',
    failed: 'error',
  };

  return (
    <SectionCard>
      <div>
        <div className="space-y-4">
          <SectionHeader
            eyebrow={t('components.terminalBench.eyebrow')}
            title={t('components.terminalBench.title')}
            size="md"
          />

          <div className="flex flex-wrap items-center gap-2" data-testid="terminal-session-controls">
            <Button
              size="sm"
              variant="primary"
              onClick={onAttach}
              disabled={!canAttach}
              isLoading={isAttaching}
            >
              {isAttaching ? t('components.terminalBench.attaching') : t('components.terminalBench.attach')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={onDetach}
              disabled={!canDetach}
              isLoading={isDetaching}
            >
              {isDetaching ? t('components.terminalBench.detaching') : t('components.terminalBench.detach')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={onReset}
              disabled={!canReset}
              isLoading={isResetting}
            >
              {isResetting ? t('components.terminalBench.resetting') : t('components.terminalBench.resetSession')}
            </Button>
            <div className="inline-flex items-center gap-1.5 rounded-full bg-[var(--bg-tertiary)] px-2.5 py-1 text-xs font-medium text-[var(--text)]">
              <StatusDot status={statusMap[status]} />
              {t('components.terminalBench.statusPrefix')} {statusLabel[status]}
            </div>
            <Button size="sm" variant="ghost" onClick={() => setDetailsOpen(true)}>
              {t('components.terminalBench.detailsAction')}
            </Button>
          </div>

          {loadError ? (
            <p className="text-xs text-[#ff3b30]">
              {t('components.terminalBench.loadError')} {loadError}
            </p>
          ) : null}
          {!selectedEnvironmentSummary ? (
            <p className="text-xs text-[#ff9500]">
              {t('components.terminalBench.selectEnvironmentBeforeAttach')}
            </p>
          ) : null}
          {!hasRuntimeError && !isLoading && status === 'idle' ? (
            <p className="text-xs text-[var(--text-tertiary)]">
              {t('components.terminalBench.noSessionYet')}
            </p>
          ) : null}
          {!hasRuntimeError && !isLoading && status === 'running' && terminalWsUrl === null ? (
            <p className="text-xs text-[var(--text-tertiary)]">
              {t('components.terminalBench.detachedNotice')}
            </p>
          ) : null}
        </div>
      </div>

      <Dialog
        isOpen={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        title={t('components.terminalBench.detailsTitle')}
        size="md"
      >
        <dl className="grid gap-3 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
          <dt className="font-medium text-[var(--text)]">{t('components.terminalBench.loading')}</dt>
          <dd className="break-words text-[var(--text-secondary)]">{isLoading ? t('common.yes') : t('common.no')}</dd>
          <dt className="font-medium text-[var(--text)]">{t('components.terminalBench.environment')}</dt>
          <dd className="break-words text-[var(--text-secondary)]">{selectedEnvironmentSummary ?? t('common.notSelected')}</dd>
          <dt className="font-medium text-[var(--text)]">{t('components.terminalBench.sessionName')}</dt>
          <dd className="break-all text-[var(--text-secondary)]">{sessionName ?? sessionId ?? t('common.unavailable')}</dd>
          <dt className="font-medium text-[var(--text)]">{t('components.terminalBench.attachment')}</dt>
          <dd className="break-all text-[var(--text-secondary)]">{attachmentId ?? t('common.unavailable')}</dd>
          <dt className="font-medium text-[var(--text)]">{t('components.terminalBench.websocketUrl')}</dt>
          <dd className="break-all text-[var(--text-secondary)]">{terminalWsUrl ?? t('common.unavailable')}</dd>
          <dt className="font-medium text-[var(--text)]">{t('common.detailLabel')}</dt>
          <dd className="break-words text-[var(--text-secondary)]">{detail ?? t('common.unavailable')}</dd>
        </dl>
      </Dialog>

      <SectionCard
        collapsible
        expanded={consoleExpanded}
        onToggle={onToggleConsole}
        header={
          <div className="text-sm font-medium text-[var(--text)]">
            {t('components.terminalBench.consoleTitle')}
          </div>
        }
      >
        <div className="min-h-[480px]">
          <TerminalSessionConsole
            sessionId={sessionId}
            attachmentId={attachmentId}
            terminalWsUrl={terminalWsUrl}
            status={status}
            onDisconnected={onTerminalDisconnected}
          />
        </div>
      </SectionCard>
    </SectionCard>
  );
}

export default TerminalBenchCardView;
