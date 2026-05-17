import SectionStack from '../../components/layout/SectionStack';
import { useT } from '../../i18n';
import type { SessionDetailRecord } from '../../types';
import { AttemptChain } from './AttemptChain';

interface Props {
  detail: SessionDetailRecord | null;
  loading: boolean;
  selectedId: string | null;
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  active: 'bg-green-100 text-green-700 border-green-200',
  completed: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  archived: 'bg-gray-100 text-gray-700 border-gray-200',
};

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function SessionDetail({ detail, loading, selectedId }: Props) {
  const t = useT();

  if (!selectedId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('pages.sessions.selectPrompt')}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('common.loading')}
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        {t('pages.sessions.notFound')}
      </div>
    );
  }

  return (
    <div className="p-4">
      <SectionStack gap={4}>
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">{detail.title}</h2>
          <span
            className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_BADGE_CLASSES[detail.status] ?? STATUS_BADGE_CLASSES.archived}`}
          >
            {t(`pages.sessions.status.${detail.status}`)}
          </span>
        </div>

        <div className="flex items-center gap-6 text-sm text-gray-600">
          <span>{t('pages.sessions.taskCount', { count: detail.task_count })}</span>
          <span>
            {t('pages.sessions.totalDuration', {
              duration: formatDuration(detail.total_duration_ms),
            })}
          </span>
          <span>${detail.total_cost_usd.toFixed(2)}</span>
        </div>

        <AttemptChain attempts={detail.attempts} />
      </SectionStack>
    </div>
  );
}
