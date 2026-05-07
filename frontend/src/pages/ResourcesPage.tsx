import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { useQuery } from '@tanstack/react-query';
import { getResources } from '../api';
import { SystemResourceCard, AinrfProcessCard, DraggableResourceCard } from '../components/resources';
import { useT } from '../i18n';
import { useCardLayout } from '../hooks/useCardLayout';
import type { CardKind } from '../hooks/useCardLayout';

const cardRenderers: Record<CardKind, (snapshot: any) => React.ReactNode> = {
  system: (snapshot) => <SystemResourceCard snapshot={snapshot} />,
  processes: (snapshot) => (
    <AinrfProcessCard processes={snapshot.ainrf_processes} environment_name={snapshot.environment_name} />
  ),
};

export default function ResourcesPage() {
  const t = useT();
  const resourcesQuery = useQuery({
    queryKey: ['resources'],
    queryFn: getResources,
    refetchInterval: 5000,
    staleTime: 4000,
  });
  const { layout, swapCards } = useCardLayout();

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

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

      <DndContext sensors={sensors} onDragEnd={(event) => {
        const { active, over } = event;
        if (over && active.id !== over.id) {
          const activeKind = (active.data.current as { kind?: CardKind } | undefined)?.kind;
          const overKind = (over.data.current as { kind?: CardKind } | undefined)?.kind;
          if (activeKind && overKind) {
            swapCards(activeKind, overKind);
          }
        }
      }}>
        {snapshots.map((snapshot) => (
          <div key={snapshot.environment_id} className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {layout.cardOrder.map((kind) => (
              <DraggableResourceCard
                key={`${snapshot.environment_id}:${kind}`}
                id={`${snapshot.environment_id}:${kind}`}
                kind={kind}
              >
                {cardRenderers[kind](snapshot)}
              </DraggableResourceCard>
            ))}
          </div>
        ))}
      </DndContext>
    </div>
  );
}
