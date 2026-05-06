import { Globe, Package, Terminal, Cpu, HardDrive, Variable, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { Modal, StatusDot, Alert } from '../ui';
import { useT } from '../../i18n';
import type { EnvironmentDetection } from '../../types';

interface EnvironmentDetectionModalProps {
  detection: EnvironmentDetection;
  environmentName: string;
  isOpen: boolean;
  onClose: () => void;
}

const statusBarColors: Record<EnvironmentDetection['status'], string> = {
  success: 'bg-emerald-500',
  partial: 'bg-amber-500',
  failed: 'bg-red-500',
};

const statusBarTextColors: Record<EnvironmentDetection['status'], string> = {
  success: 'text-emerald-600',
  partial: 'text-amber-600',
  failed: 'text-red-600',
};

const statusBarBgColors: Record<EnvironmentDetection['status'], string> = {
  success: 'bg-emerald-50',
  partial: 'bg-amber-50',
  failed: 'bg-red-50',
};

function ToolStatusRow({ label, tool }: { label: string; tool: EnvironmentDetection['python'] }) {
  const t = useT();
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
      <span className="inline-flex items-center gap-1.5 text-sm text-[var(--text)]">
        <StatusDot status={tool.available ? 'success' : 'error'} />
        <span>{tool.available ? t('components.environmentDetectionModal.status.available') : t('components.environmentDetectionModal.status.unavailable')}</span>
        {tool.version ? (
          <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{tool.version}</code>
        ) : null}
      </span>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-[var(--text-secondary)]">{label}</span>
      <span className="text-sm text-[var(--text)]">{value ?? '—'}</span>
    </div>
  );
}

function GroupCard({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[var(--text-secondary)]">{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          {title}
        </span>
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export default function EnvironmentDetectionModal({
  detection,
  environmentName,
  isOpen,
  onClose,
}: EnvironmentDetectionModalProps) {
  const t = useT();
  const statusColor = statusBarColors[detection.status];
  const statusTextColor = statusBarTextColors[detection.status];
  const statusBgColor = statusBarBgColors[detection.status];

  const statusLabelMap: Record<EnvironmentDetection['status'], string> = {
    success: t('pages.environments.detectionStatus.success'),
    partial: t('pages.environments.detectionStatus.partial'),
    failed: t('pages.environments.detectionStatus.failed'),
  };
  const statusLabel = statusLabelMap[detection.status];

  const StatusIcon = detection.status === 'success' ? CheckCircle2 : detection.status === 'partial' ? AlertTriangle : XCircle;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`${environmentName} · ${t('pages.environments.detection')}`}
      size="xl"
    >
      <div className="space-y-4">
        {/* Status bar */}
        <div className={`flex items-center gap-3 rounded-lg ${statusBgColor} p-3`}>
          <div className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
          <StatusIcon size={18} className={statusTextColor} />
          <span className={`text-sm font-medium ${statusTextColor}`}>{statusLabel}</span>
          {detection.summary ? (
            <span className="text-sm text-[var(--text-secondary)]">{detection.summary}</span>
          ) : null}
        </div>

        {/* Group cards */}
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Basic Info */}
          <GroupCard icon={<Globe size={16} />} title={t('components.environmentDetectionModal.groups.basicInfo')}>
            <InfoRow label={t('components.environmentDetectionModal.labels.ssh')} value={detection.ssh_ok ? t('common.ok') : t('common.failed')} />
            <InfoRow label={t('components.environmentDetectionModal.labels.hostname')} value={detection.hostname} />
            <InfoRow label={t('components.environmentDetectionModal.labels.os')} value={detection.os_info} />
            <InfoRow label={t('components.environmentDetectionModal.labels.arch')} value={detection.arch} />
            <InfoRow
              label={t('components.environmentDetectionModal.labels.workdir')}
              value={detection.workdir_exists === null ? null : detection.workdir_exists ? t('common.yes') : t('common.no')}
            />
          </GroupCard>

          {/* Python Toolchain */}
          <GroupCard icon={<Package size={16} />} title={t('components.environmentDetectionModal.groups.pythonToolchain')}>
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.python')} tool={detection.python} />
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.conda')} tool={detection.conda} />
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.uv')} tool={detection.uv} />
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.pixi')} tool={detection.pixi} />
          </GroupCard>

          {/* Dev Tools */}
          <GroupCard icon={<Terminal size={16} />} title={t('components.environmentDetectionModal.groups.devTools')}>
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.codeServer')} tool={detection.code_server} />
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.claudeCli')} tool={detection.claude_cli} />
          </GroupCard>

          {/* AI / ML */}
          <GroupCard icon={<Cpu size={16} />} title={t('components.environmentDetectionModal.groups.aiMl')}>
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.torch')} tool={detection.torch} />
            <ToolStatusRow label={t('components.environmentDetectionModal.labels.cuda')} tool={detection.cuda} />
          </GroupCard>

          {/* GPU Info */}
          <GroupCard icon={<HardDrive size={16} />} title={t('components.environmentDetectionModal.groups.gpu')}>
            <InfoRow label={t('components.environmentDetectionModal.labels.gpuCount')} value={detection.gpu_count} />
            <InfoRow
              label={t('components.environmentDetectionModal.labels.gpuModels')}
              value={detection.gpu_models.length > 0 ? detection.gpu_models.join(', ') : t('common.no')}
            />
          </GroupCard>

          {/* Environment Variables */}
          <GroupCard icon={<Variable size={16} />} title={t('components.environmentDetectionModal.groups.envVars')}>
            <div className="flex items-center justify-between py-1">
              <span className="text-sm text-[var(--text-secondary)]">{t('components.environmentDetectionModal.labels.anthropic')}</span>
              <span className="inline-flex items-center gap-1.5 text-sm text-[var(--text)]">
                <StatusDot
                  status={
                    detection.anthropic_env === 'present'
                      ? 'success'
                      : detection.anthropic_env === 'missing'
                        ? 'error'
                        : 'idle'
                  }
                />
                <span>
                  {detection.anthropic_env === 'present'
                    ? t('components.environmentDetectionModal.status.present')
                    : detection.anthropic_env === 'missing'
                      ? t('components.environmentDetectionModal.status.missing')
                      : t('components.environmentDetectionModal.status.unknown')}
                </span>
              </span>
            </div>
          </GroupCard>
        </div>

        {/* Errors */}
        {detection.errors.length > 0 ? (
          <div className="space-y-2">
            {detection.errors.map((error, index) => (
              <Alert key={`error-${index}`} variant="error">
                {error}
              </Alert>
            ))}
          </div>
        ) : null}

        {/* Warnings */}
        {detection.warnings.length > 0 ? (
          <div className="space-y-2">
            {detection.warnings.map((warning, index) => (
              <Alert key={`warning-${index}`} variant="warning">
                {warning}
              </Alert>
            ))}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
