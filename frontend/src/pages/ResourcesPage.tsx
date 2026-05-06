import { useQuery } from '@tanstack/react-query';
import { getResources } from '../api';
import { SystemResourceCard, AinrfProcessCard } from '../components/resources';
import { useT } from '../i18n';

export default function ResourcesPage() {
  const t = useT();
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: getResources,
    refetchInterval: 5000,
    staleTime: 4000,
  });

  const snapshots = resourcesQuery.data?.items ?? [];

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
          {t('pages.resources.eyebrow')}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{t('pages.resources.title')}</h1>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          {t('pages.resources.description')}
        </p>
      </div>

      {resourcesQuery.isLoading && snapshots.length === 0 && (
        <p className="text-sm text-[var(--text-tertiary)]">{t('pages.resources.loading')}</p>
      )}

      {snapshots.length === 0 && !resourcesQuery.isLoading && (
        <p className="text-sm text-[var(--text-tertiary)]">{t('pages.resources.noData')}</p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {snapshots.map((snapshot) => (
          <div key={snapshot.environment_id} className="space-y-4">
            <SystemResourceCard snapshot={snapshot} />
            <AinrfProcessCard
              processes={snapshot.ainrf_processes}
              environment_name={snapshot.environment_name}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
