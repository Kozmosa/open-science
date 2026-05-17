import SectionStack from '../../components/layout/SectionStack';
import { useT } from '../../i18n';
import type { AttemptRecord } from '../../types';

interface Props {
  attempts: AttemptRecord[];
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  running: 'bg-blue-100 text-blue-700 border-blue-200',
  completed: 'bg-green-100 text-green-700 border-green-200',
  failed: 'bg-red-100 text-red-700 border-red-200',
  interrupted: 'bg-yellow-100 text-yellow-700 border-yellow-200',
};

function formatDuration(ms: number | null): string {
  if (ms === null) return '--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function AttemptChain({ attempts }: Props) {
  const t = useT();

  if (attempts.length === 0) {
    return <p className="text-sm text-gray-400">{t('pages.sessions.noAttempts')}</p>;
  }

  return (
    <SectionStack gap={2}>
      <h3 className="text-sm font-semibold text-gray-700">
        {t('pages.sessions.attemptsTitle')}
      </h3>
      <div className="relative pl-6">
        {attempts.map((a, i) => (
          <div key={a.id} className="relative pb-4 last:pb-0">
            {/* Timeline dot */}
            <div
              className={`absolute left-[-22px] top-[14px] w-3 h-3 rounded-full border-2 border-white z-10 ${
                a.status === 'running'
                  ? 'bg-blue-500 shadow-[0_0_0_2px_#bfdbfe]'
                  : a.status === 'completed'
                    ? 'bg-green-500'
                    : a.status === 'failed'
                      ? 'bg-red-500'
                      : 'bg-gray-400'
              }`}
            />
            {/* Connector line */}
            {i < attempts.length - 1 && (
              <div className="absolute left-[-16.5px] top-[26px] w-[1px] h-full bg-gray-200" />
            )}

            <div
              className={`rounded-lg border p-3 ${
                a.status === 'running'
                  ? 'bg-blue-50 border-blue-200'
                  : a.status === 'completed'
                    ? 'bg-green-50 border-green-200'
                    : a.status === 'failed'
                      ? 'bg-red-50 border-red-200'
                      : 'bg-yellow-50 border-yellow-200'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-sm">
                  {t('pages.sessions.attemptLabel', { seq: a.attempt_seq })}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE_CLASSES[a.status] ?? STATUS_BADGE_CLASSES.interrupted}`}
                >
                  {t(`pages.sessions.attemptStatus.${a.status}`)}
                </span>
              </div>
              {a.intervention_reason && (
                <p className="text-xs text-gray-500 mt-1">{a.intervention_reason}</p>
              )}
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                {a.task_id && (
                  <a
                    href={`/tasks/${a.task_id}`}
                    className="text-blue-600 hover:underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {t('pages.sessions.viewTask')}
                  </a>
                )}
                <span>{formatDuration(a.duration_ms)}</span>
                {a.token_usage_json && (
                  <span className="text-gray-400">
                    {t('pages.sessions.hasTokens')}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </SectionStack>
  );
}
