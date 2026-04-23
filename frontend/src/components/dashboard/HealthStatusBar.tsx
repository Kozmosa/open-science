import type { SystemHealth } from '../../types';
import { useT } from '../../i18n';

interface Props {
  health: SystemHealth | undefined;
  isLoading: boolean;
}

function StatusDot({ active }: { active: boolean; color?: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${active ? 'bg-[#34c759]' : 'bg-[#ff3b30]'}`}
    />
  );
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
      <StatusDot active={active} />
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
      <div className="flex items-center gap-2 rounded-lg bg-[#ffebee] px-4 py-3 text-sm text-[#c62828]">
        <span className="inline-block h-2 w-2 rounded-full bg-[#ff3b30]" />
        {t('components.healthStatusBar.unable')}
      </div>
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
