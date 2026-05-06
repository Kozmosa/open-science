import type { GpuInfo } from '../../types';

function formatMB(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }
  return `${mb} MB`;
}

function getBarColor(percent: number): string {
  if (percent < 50) return 'bg-emerald-500';
  if (percent < 80) return 'bg-amber-500';
  return 'bg-red-500';
}

interface GpuBarProps {
  gpus: GpuInfo[];
}

export default function GpuBar({ gpus }: GpuBarProps) {
  if (gpus.length === 0) {
    return <p className="text-sm text-[var(--text-tertiary)]">No GPU detected</p>;
  }

  return (
    <div className="space-y-3">
      {gpus.map((gpu) => (
        <div key={gpu.index} className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-[var(--foreground)]">
              GPU {gpu.index}: {gpu.name}
            </span>
            <span className="text-[var(--text-tertiary)]">
              {gpu.utilization_percent}% | {formatMB(gpu.memory_used_mb)} / {formatMB(gpu.memory_total_mb)}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--bg-tertiary)]">
            <div
              className={`h-full rounded-full transition-all duration-500 ${getBarColor(gpu.utilization_percent)}`}
              style={{ width: `${Math.min(gpu.utilization_percent, 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
