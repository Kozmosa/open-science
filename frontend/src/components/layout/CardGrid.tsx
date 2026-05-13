import { useCallback, useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { DndContext, PointerSensor, useSensor, useSensors, useDraggable, useDroppable } from '@dnd-kit/core';
import type { DragEndEvent } from '@dnd-kit/core';

interface CardGroup {
  id: string;
  cards: { id: string; kind: string }[];
}

interface CardGridProps {
  groups: CardGroup[];
  renderCard: (cardId: string, kind: string, groupId: string) => ReactNode;
  cardOrder: string[];
  onCardOrderChange: (order: string[]) => void;
  storageKey: string;
  columns?: number;
  gap?: number;
  className?: string;
}

// ── DraggableCard ─────────────────────────────────────────────
interface DraggableCardProps {
  id: string;
  kind: string;
  groupId: string;
  children: ReactNode;
}

function DraggableCard({ id, kind, groupId, children }: DraggableCardProps) {
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } = useDraggable({
    id,
    data: { kind, groupId },
  });
  const { setNodeRef: setDropRef } = useDroppable({
    id,
    data: { kind, groupId },
  });

  const style: React.CSSProperties = {
    transform: transform ? `translate3d(${transform.x}px, ${transform.y}px, 0)` : undefined,
    opacity: isDragging ? 0.5 : 1,
    transition: 'opacity 150ms ease',
  };

  return (
    <div ref={setDropRef} style={style} className="relative">
      <div
        ref={setDragRef}
        {...listeners}
        {...attributes}
        className="absolute right-3 top-3 cursor-grab active:cursor-grabbing"
        title="Drag to reorder"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          className="text-[var(--text-tertiary)]"
        >
          <circle cx="4" cy="4" r="1.5" />
          <circle cx="8" cy="4" r="1.5" />
          <circle cx="12" cy="4" r="1.5" />
          <circle cx="4" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="12" cy="8" r="1.5" />
          <circle cx="4" cy="12" r="1.5" />
          <circle cx="8" cy="12" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
        </svg>
      </div>
      {children}
    </div>
  );
}

// ── Storage helpers ───────────────────────────────────────────
function writeOrder(storageKey: string, order: string[]): void {
  try {
    window.localStorage.setItem(`card-grid:${storageKey}`, JSON.stringify(order));
  } catch {
    // ignore
  }
}

const GAP_CLASSES: Record<number, string> = { 2: 'gap-2', 3: 'gap-3', 4: 'gap-4', 5: 'gap-5', 6: 'gap-6', 8: 'gap-8' };
const COL_CLASSES: Record<number, string> = { 1: 'lg:grid-cols-1', 2: 'lg:grid-cols-2', 3: 'lg:grid-cols-3', 4: 'lg:grid-cols-4' };

// ── CardGrid ──────────────────────────────────────────────────
export default function CardGrid({
  groups,
  renderCard,
  cardOrder,
  onCardOrderChange,
  storageKey,
  columns = 2,
  gap = 6,
  className,
}: CardGridProps) {
  const initialisedRef = useRef(false);

  // Persist on every cardOrder change (skip initial call)
  useEffect(() => {
    if (!initialisedRef.current) {
      initialisedRef.current = true;
      return;
    }
    writeOrder(storageKey, cardOrder);
  }, [storageKey, cardOrder]);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    })
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const activeKind = String(active.id).split(':')[1];
      const overKind = String(over.id).split(':')[1];
      if (!activeKind || !overKind) return;

      const activeIndex = cardOrder.indexOf(activeKind);
      const overIndex = cardOrder.indexOf(overKind);
      if (activeIndex === -1 || overIndex === -1) return;

      const newOrder = [...cardOrder];
      const [removed] = newOrder.splice(activeIndex, 1);
      newOrder.splice(overIndex, 0, removed);
      onCardOrderChange(newOrder);
    },
    [cardOrder, onCardOrderChange]
  );

  const gapClass = GAP_CLASSES[gap] ?? GAP_CLASSES[6];
  const colClass = COL_CLASSES[columns] ?? COL_CLASSES[2];

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
      <div className={`${gapClass} ${className ?? ''}`}>
        {groups.map((group) => (
          <div key={group.id} className={`grid grid-cols-1 ${gapClass} ${colClass}`}>
            {cardOrder.map((kind) => {
              const card = group.cards.find((c) => c.kind === kind);
              if (!card) return null;
              return (
                <DraggableCard
                  key={`${group.id}:${kind}`}
                  id={`${group.id}:${kind}`}
                  kind={kind}
                  groupId={group.id}
                >
                  {renderCard(card.id, kind, group.id)}
                </DraggableCard>
              );
            })}
          </div>
        ))}
      </div>
    </DndContext>
  );
}
