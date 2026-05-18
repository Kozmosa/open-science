import type { AttemptRecord } from '../../types';

interface Props {
  attempt: AttemptRecord;
  leftPct: number;
  widthPct: number;
  onClick: () => void;
}

const STATUS_COLOR: Record<string, string> = {
  completed: 'bg-green-300 border-green-400',
  running: 'bg-blue-300 border-blue-400',
  failed: 'bg-red-300 border-red-400',
  interrupted: 'bg-yellow-300 border-yellow-400',
};

function formatDuration(ms: number | null): string {
  if (ms === null) return '--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function AttemptSegment({ attempt, leftPct, widthPct, onClick }: Props) {
  const tooltip = [
    `Attempt #${attempt.attempt_seq}`,
    `Status: ${attempt.status}`,
    `Duration: ${formatDuration(attempt.duration_ms)}`,
    attempt.intervention_reason ? `Reason: ${attempt.intervention_reason}` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div
      className={`absolute h-3 rounded-sm border cursor-pointer transition-opacity hover:opacity-80 ${STATUS_COLOR[attempt.status] ?? 'bg-gray-300 border-gray-400'}`}
      style={{ left: `${leftPct}%`, width: `${widthPct}%`, top: '8px' }}
      title={tooltip}
      onClick={onClick}
    />
  );
}
