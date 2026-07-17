import { useT } from '@/shared/i18n';

interface CpuRingProps {
  percent: number;
  core_count: number;
}

function getColor(percent: number): string {
  if (percent < 50) return 'var(--osci-color-success)';
  if (percent < 80) return 'var(--osci-color-warning)';
  return 'var(--osci-color-danger)';
}

export default function CpuRing({ percent, core_count }: CpuRingProps) {
  const t = useT();
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.min(percent, 100) / 100) * circumference;
  const color = getColor(percent);

  return (
    <div className="flex items-center gap-4">
      <div className="relative h-20 w-20">
        <svg className="h-full w-full -rotate-90" viewBox="0 0 80 80">
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="none"
            stroke="var(--osci-color-surface-subtle)"
            strokeWidth="8"
          />
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="transition-all duration-500"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-semibold leading-none">{Math.round(percent)}%</span>
        </div>
      </div>
      <div>
        <p className="text-xs text-[var(--osci-color-text-muted)]">{t('components.resources.cpu')}</p>
        <p className="text-sm font-medium">{core_count} {t('components.resources.cores')}</p>
      </div>
    </div>
  );
}
