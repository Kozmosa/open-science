import type { ResourceSnapshot } from '@/shared/types';
import { useT } from '@/shared/i18n';
import GpuBar from './GpuBar';
import CpuRing from './CpuRing';
import MemoryBar from './MemoryBar';
import { StatusDot } from '@design-system';

interface SystemResourceCardProps {
  snapshot: ResourceSnapshot;
}

export default function SystemResourceCard({ snapshot }: SystemResourceCardProps) {
  const t = useT();

  return (
    <div className="h-full rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusDot status={snapshot.status === 'ok' ? 'success' : snapshot.status === 'degraded' ? 'warning' : 'error'} />
          <h3 className="text-sm font-semibold">{snapshot.environment_name}</h3>
        </div>
        <span className="text-xs text-[var(--osci-color-text-muted)]">
          {new Date(snapshot.timestamp).toLocaleTimeString()}
        </span>
      </div>

      <div className="space-y-5">
        <div>
          <p className="mb-2 text-xs font-medium text-[var(--osci-color-text-secondary)]">
            {t('pages.resources.systemCard.gpuTitle')}
          </p>
          <GpuBar gpus={snapshot.gpus} />
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-[var(--osci-color-text-secondary)]">
            {t('pages.resources.systemCard.cpuTitle')}
          </p>
          <CpuRing percent={snapshot.cpu.percent} core_count={snapshot.cpu.core_count} />
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-[var(--osci-color-text-secondary)]">
            {t('pages.resources.systemCard.memoryTitle')}
          </p>
          <MemoryBar used_mb={snapshot.memory.used_mb} total_mb={snapshot.memory.total_mb} />
        </div>
      </div>
    </div>
  );
}
