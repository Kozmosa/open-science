interface CpuRingProps {
  percent: number;
  core_count: number;
}

function getColor(percent: number): string {
  if (percent < 50) return '#10b981';
  if (percent < 80) return '#f59e0b';
  return '#ef4444';
}

export default function CpuRing({ percent, core_count }: CpuRingProps) {
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
            stroke="var(--bg-tertiary)"
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
        <p className="text-xs text-[var(--text-tertiary)]">CPU Usage</p>
        <p className="text-sm font-medium">{core_count} cores</p>
      </div>
    </div>
  );
}
