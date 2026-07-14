import { useT } from '@/shared/i18n';

function formatMB(mb: number): string {
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }
  return `${mb} MB`;
}

interface MemoryBarProps {
  used_mb: number;
  total_mb: number;
}

export default function MemoryBar({ used_mb, total_mb }: MemoryBarProps) {
  const t = useT();
  const percent = total_mb > 0 ? Math.round((used_mb / total_mb) * 100) : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium">{t('components.resources.memory')}</span>
        <span className="text-[var(--osci-color-text-muted)]">
          {formatMB(used_mb)} / {formatMB(total_mb)} ({percent}%)
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--osci-color-surface-subtle)]">
        <div
          className="h-full rounded-full bg-[var(--osci-color-primary)] transition-all duration-500"
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
    </div>
  );
}
