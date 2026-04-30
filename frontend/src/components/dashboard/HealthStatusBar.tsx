import { Alert, StatusDot } from '../ui';
import type { SystemHealth } from '../../types';
import { useT } from '../../i18n';

interface Props {
  health: SystemHealth | undefined;
  isLoading: boolean;
}

function StatusItem({
  label,
  active,
  text,
}: {
  label: string;
  active: boolean;
  text: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <StatusDot status={active ? 'success' : 'error'} />
      <span className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        {label} <span className="font-medium text-[var(--text)]">{text}</span>
      </span>
    </div>
  );
}

function HealthStatusBar({ health, isLoading }: Props) {
  const t = useT();

  if (isLoading) {
    return (
      <div className="rounded-lg bg-[var(--bg-tertiary)] px-4 py-3 text-sm text-[var(--text-tertiary)]">
        {t('components.healthStatusBar.loading')}
      </div>
    );
  }

  if (!health) {
    return (
      <Alert variant="error">
        <div className="flex items-center gap-2">
          <StatusDot status="error" />
          {t('components.healthStatusBar.unable')}
        </div>
      </Alert>
    );
  }

  const sshOk = health.container_health?.ssh_ok ?? false;
  const workspaceReady = health.container_health?.project_dir_writable ?? false;
  const containerConfigured = health.container_configured
    ? t('common.configured')
    : t('common.notConfigured');
  const apiStatus = health.status === 'ok' ? t('common.ok') : t('common.degraded');

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg bg-[var(--bg-tertiary)] px-4 py-3">
      <StatusItem
        label={t('components.healthStatusBar.apiLabel')}
        active={health.status === 'ok'}
        text={apiStatus}
      />
      <StatusItem
        label={t('components.healthStatusBar.containerLabel')}
        active={health.container_configured}
        text={containerConfigured}
      />
      <StatusItem
        label={t('components.healthStatusBar.sshLabel')}
        active={sshOk}
        text={sshOk ? t('common.available') : t('common.unavailable')}
      />
      <StatusItem
        label={t('components.healthStatusBar.workspaceLabel')}
        active={workspaceReady}
        text={workspaceReady ? t('common.writable') : t('common.notReady')}
      />
    </div>
  );
}

export default HealthStatusBar;
