import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { getResources, getTaskTokenUsageSummary } from '@/shared/api';
import { OpenScienceProcessCard, SystemResourceCard, TaskUsageCard } from '@/components/resources';
import { useT } from '@/shared/i18n';
import { useCardLayout, type CardKind } from '@/hooks/useCardLayout';
import { Button, CardGrid, EmptyState, PageHeader, PageShell, Skeleton, UpdateStrip } from '@design-system';
import { queryKeys } from '@/shared/api/queryKeys';
import { useAuth } from '@features/auth';
import { RESOURCE_STALE_MS, resourceRefreshInterval } from '@features/resources/refreshPolicy';

function usePageVisibility(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return visible;
}

function formatTimestamp(value: number): string {
  return new Date(value).toLocaleTimeString();
}

export default function ResourcesPage() {
  const t = useT();
  const { user } = useAuth();
  const pageVisible = usePageVisibility();
  const wasVisibleRef = useRef(pageVisible);
  const resourcesQuery = useQuery({
    queryKey: queryKeys.resources.all,
    queryFn: getResources,
    refetchInterval: resourceRefreshInterval(pageVisible),
    refetchIntervalInBackground: false,
    staleTime: 4_000,
  });
  const tokenUsageQuery = useQuery({
    queryKey: queryKeys.tasks.tokenUsage({ includeArchived: true }),
    queryFn: () => getTaskTokenUsageSummary({ includeArchived: true }),
    refetchInterval: pageVisible ? 15_000 : false,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
  const { layout, setLayout } = useCardLayout(user?.id ?? 'anonymous');

  useEffect(() => {
    if (pageVisible && !wasVisibleRef.current) {
      void resourcesQuery.refetch();
      void tokenUsageQuery.refetch();
    }
    wasVisibleRef.current = pageVisible;
  // Refetch functions are stable query observers; visibility is the event boundary.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageVisible]);

  const snapshots = useMemo(() => resourcesQuery.data?.items ?? [], [resourcesQuery.data]);
  const hasResourceData = snapshots.length > 0;
  const hasTokenUsageData = tokenUsageQuery.data != null;
  const hasAnyData = hasResourceData || hasTokenUsageData;
  const groups = useMemo(() => [
    ...(tokenUsageQuery.data != null || tokenUsageQuery.isLoading
      ? [{ id: 'global', cards: [{ id: 'global:taskUsage', kind: 'taskUsage' }] }]
      : []),
    ...snapshots.map((snapshot) => ({
      id: snapshot.environment_id,
      cards: [
        { id: `${snapshot.environment_id}:system`, kind: 'system' },
        { id: `${snapshot.environment_id}:processes`, kind: 'processes' },
      ],
    })),
  ], [snapshots, tokenUsageQuery.data, tokenUsageQuery.isLoading]);

  const renderCard = useCallback((_cardId: string, kind: string, groupId: string) => {
    if (kind === 'taskUsage') {
      return <TaskUsageCard summary={tokenUsageQuery.data ?? null} loading={tokenUsageQuery.isLoading} />;
    }
    const snapshot = snapshots.find((item) => item.environment_id === groupId);
    if (!snapshot) return null;
    return kind === 'system'
      ? <SystemResourceCard snapshot={snapshot} />
      : <OpenScienceProcessCard processes={snapshot.ainrf_processes} environment_name={snapshot.environment_name} />;
  }, [snapshots, tokenUsageQuery.data, tokenUsageQuery.isLoading]);

  const lastSuccessfulAt = Math.max(resourcesQuery.dataUpdatedAt, tokenUsageQuery.dataUpdatedAt);
  const anySourceLoading = resourcesQuery.isLoading || tokenUsageQuery.isLoading;
  const anySourceFailure = resourcesQuery.isError || tokenUsageQuery.isError;
  const anyRefetchFailure = resourcesQuery.isRefetchError || tokenUsageQuery.isRefetchError;
  const globalFailure = !hasAnyData && !anySourceLoading && anySourceFailure;
  const partialFailure = hasAnyData && (anySourceFailure || snapshots.some((snapshot) => snapshot.status !== 'ok'));
  const stale = lastSuccessfulAt > 0 && (Date.now() - lastSuccessfulAt > RESOURCE_STALE_MS || anyRefetchFailure);
  const stripTone = globalFailure ? 'danger' : partialFailure || stale || anyRefetchFailure ? 'warning' : 'success';
  const stripMessage = globalFailure
    ? t('pages.resources.refreshFailed')
    : anyRefetchFailure
      ? t('pages.resources.showingPrevious')
      : partialFailure
        ? t('pages.resources.partial')
        : stale
          ? t('pages.resources.stale')
          : lastSuccessfulAt > 0
            ? t('pages.resources.lastUpdated', { time: formatTimestamp(lastSuccessfulAt) })
            : t('pages.resources.loading');

  const refresh = () => {
    void resourcesQuery.refetch();
    void tokenUsageQuery.refetch();
  };

  return (
    <PageShell variant="canvas">
      <div className="flex flex-col gap-5 p-4 md:p-6">
        <PageHeader
          eyebrow={t('pages.resources.eyebrow')}
          title={t('pages.resources.title')}
          description={t('pages.resources.description')}
          actions={(
            <Button variant="secondary" size="sm" onClick={refresh} isLoading={resourcesQuery.isFetching || tokenUsageQuery.isFetching} className="gap-2">
              <RefreshCw aria-hidden="true" size={14} />
              {t('pages.resources.refresh')}
            </Button>
          )}
        />

        <UpdateStrip tone={stripTone} data-testid="resources-update-strip">
          <span>{stripMessage}</span>
          {!pageVisible ? <span className="ml-2">{t('pages.resources.paused')}</span> : null}
          {hasAnyData && lastSuccessfulAt > 0 && (globalFailure || partialFailure || stale || anyRefetchFailure)
            ? <span className="ml-2 text-xs">{t('pages.resources.lastUpdated', { time: formatTimestamp(lastSuccessfulAt) })}</span>
            : null}
        </UpdateStrip>

        {anySourceLoading && !hasAnyData ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-80" /><Skeleton className="h-80" /><Skeleton className="h-80" />
          </div>
        ) : null}

        {!anySourceLoading && !hasAnyData ? (
          <EmptyState message={globalFailure ? t('pages.resources.refreshFailed') : t('pages.resources.noData')} />
        ) : null}

        {hasAnyData ? (
          <CardGrid
            groups={groups}
            renderCard={renderCard}
            cardOrder={layout.cardOrder}
            onCardOrderChange={(order) => setLayout({ cardOrder: order as CardKind[] })}
            columns={3}
            className="items-stretch [&>div]:min-h-80"
          />
        ) : null}
      </div>
    </PageShell>
  );
}
