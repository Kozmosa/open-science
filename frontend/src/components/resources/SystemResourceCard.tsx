import type { ResourceSnapshot } from '../../types';
import { useT } from '../../i18n';
import GpuBar from './GpuBar';
import CpuRing from './CpuRing';
import MemoryBar from './MemoryBar';

interface SystemResourceCardProps {
  snapshot: ResourceSnapshot;
}

function StatusDot({ status }: { status: ResourceSnapshot['status'] }) {
  const color =
    status === 'ok' ? 'bg-emerald-500' : status === 'degraded' ? 'bg-amber-500' : 'bg-red-500';
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export default function SystemResourceCard({ snapshot }: SystemResourceCardProps) {
  const t = useT();

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusDot status={snapshot.status} />
          <h3 className="text-sm font-semibold">{snapshot.environment_name}</h3>
        </div>
        <span className="text-xs text-[var(--text-tertiary)]">
          {new Date(snapshot.timestamp).toLocaleTimeString()}
        </span>
      </div>

      <div className="space-y-5">
        <div>
          <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.resources.systemCard.gpuTitle')}
          </p>
          <GpuBar gpus={snapshot.gpus} />
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.resources.systemCard.cpuTitle')}
          </p>
          <CpuRing percent={snapshot.cpu.percent} core_count={snapshot.cpu.core_count} />
        </div>

        <div>
          <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.resources.systemCard.memoryTitle')}
          </p>
          <MemoryBar used_mb={snapshot.memory.used_mb} total_mb={snapshot.memory.total_mb} />
        </div>
      </div>
    </div>
  );
}
