import type { CSSProperties, ReactNode } from 'react';
import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';

interface CardGroup {
  id: string;
  cards: { id: string; kind: string }[];
}

interface CardGridProps {
  groups: CardGroup[];
  renderCard: (cardId: string, kind: string, groupId: string) => ReactNode;
  cardOrder: string[];
  onCardOrderChange: (order: string[]) => void;
  columns?: number;
  gap?: number;
  className?: string;
  pinnedKinds?: string[];
}

function DraggableCard({ id, kind, groupId, pinned, children }: {
  id: string;
  kind: string;
  groupId: string;
  pinned: boolean;
  children: ReactNode;
}) {
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } = useDraggable({
    id,
    disabled: pinned,
    data: { kind, groupId },
  });
  const { setNodeRef: setDropRef } = useDroppable({ id, data: { kind, groupId } });
  const t = useT();
  const style: CSSProperties = {
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    opacity: isDragging ? 0.5 : 1,
    transition: 'opacity 150ms ease',
  };

  return (
    <div ref={setDropRef} style={style} className="relative">
      {pinned ? null : (
        <button
          ref={setDragRef}
          type="button"
          {...listeners}
          {...attributes}
          className="absolute right-3 top-3 z-10 inline-flex h-7 w-7 cursor-grab items-center justify-center rounded-[var(--osci-radius-sm)] text-[var(--osci-color-text-muted)] hover:bg-[var(--osci-color-surface-subtle)] active:cursor-grabbing"
          title={t('common.dragToReorder')}
          aria-label={t('common.dragToReorder')}
        >
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <circle cx="4" cy="4" r="1.5" /><circle cx="8" cy="4" r="1.5" /><circle cx="12" cy="4" r="1.5" />
            <circle cx="4" cy="8" r="1.5" /><circle cx="8" cy="8" r="1.5" /><circle cx="12" cy="8" r="1.5" />
            <circle cx="4" cy="12" r="1.5" /><circle cx="8" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" />
          </svg>
        </button>
      )}
      {children}
    </div>
  );
}

const GAP_CLASSES: Record<number, string> = { 2: 'gap-2', 3: 'gap-3', 4: 'gap-4', 5: 'gap-5', 6: 'gap-6', 8: 'gap-8' };
const COLUMN_CLASSES: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 md:grid-cols-2',
  3: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3',
  4: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-4',
};

export default function CardGrid({ groups, renderCard, cardOrder, onCardOrderChange, columns = 2, gap = 6, className, pinnedKinds = ['attention'] }: CardGridProps) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const pinnedSet = new Set(pinnedKinds);
  const availableKinds = new Set(groups.flatMap((group) => group.cards.map((card) => card.kind)));
  const effectiveOrder = [
    ...pinnedKinds.filter((kind) => availableKinds.has(kind)),
    ...cardOrder.filter((kind) => !pinnedSet.has(kind)),
  ];

  const handleDragEnd = (event: DragEndEvent) => {
    const activeKind = event.active.data.current?.kind as string | undefined;
    const overKind = event.over?.data.current?.kind as string | undefined;
    if (!activeKind || !overKind || activeKind === overKind || pinnedSet.has(activeKind) || pinnedSet.has(overKind)) return;
    const activeIndex = effectiveOrder.indexOf(activeKind);
    const overIndex = effectiveOrder.indexOf(overKind);
    if (activeIndex < 0 || overIndex < 0) return;
    const next = [...effectiveOrder];
    const [removed] = next.splice(activeIndex, 1);
    next.splice(overIndex, 0, removed);
    onCardOrderChange(next);
  };

  const allCards = effectiveOrder.flatMap((kind) => groups.flatMap((group) => {
    const card = group.cards.find((candidate) => candidate.kind === kind);
    return card ? [{ id: card.id, kind, groupId: group.id, key: `${group.id}:${kind}` }] : [];
  }));

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className={cn('grid', COLUMN_CLASSES[Math.min(4, Math.max(1, columns))] ?? COLUMN_CLASSES[2], GAP_CLASSES[gap] ?? GAP_CLASSES[6], className)}>
        {allCards.map((card) => (
          <DraggableCard key={card.key} id={card.key} kind={card.kind} groupId={card.groupId} pinned={pinnedSet.has(card.kind)}>
            {renderCard(card.id, card.kind, card.groupId)}
          </DraggableCard>
        ))}
      </div>
    </DndContext>
  );
}
