import { useMemo, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getResources } from '../api';
import { SystemResourceCard, AinrfProcessCard } from '../components/resources';
import { useT } from '../i18n';
import { useCardLayout } from '../hooks/useCardLayout';
import type { CardKind } from '../hooks/useCardLayout';
import { CardGrid, PageShell } from '../components/layout';


export default function ResourcesPage() {
  const t = useT();
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: getResources,
    refetchInterval: 5000,
    staleTime: 4000,
  });
  const { layout, setLayout } = useCardLayout();

  const snapshots = resourcesQuery.data?.items ?? [];

  const groups = useMemo(
    () =>
      snapshots.map((snapshot) => ({
        id: snapshot.environment_id,
        cards: [
          { id: `${snapshot.environment_id}:system`, kind: 'system' },
          { id: `${snapshot.environment_id}:processes`, kind: 'processes' },
        ],
      })),
    [snapshots]
  );

  const renderCard = useCallback(
    (_cardId: string, kind: string, groupId: string) => {
      const snapshot = snapshots.find((s) => s.environment_id === groupId);
      if (!snapshot) return null;
      return kind === 'system' ? (
        <SystemResourceCard snapshot={snapshot} />
      ) : (
        <AinrfProcessCard processes={snapshot.ainrf_processes} environment_name={snapshot.environment_name} />
      );
    },
    [snapshots]
  );

  return (
    <PageShell>
      <div className="space-y-8 p-4">
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

        <CardGrid
          groups={groups}
          renderCard={renderCard}
          cardOrder={layout.cardOrder}
          onCardOrderChange={(order) => setLayout({ cardOrder: order as CardKind[] })}
          storageKey="scholar-agent:resources-layout"
        />
      </div>
    </PageShell>
  );
}
