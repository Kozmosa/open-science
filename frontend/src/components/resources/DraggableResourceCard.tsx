import { useDraggable, useDroppable } from '@dnd-kit/core';
import type { CardKind } from '../../hooks/useCardLayout';

interface Props {
  id: string;
  kind: CardKind;
  children: React.ReactNode;
}

export default function DraggableResourceCard({ id, kind, children }: Props) {
  const { attributes, listeners, setNodeRef: setDragRef, transform, isDragging } = useDraggable({
    id,
    data: { kind },
  });
  const { setNodeRef: setDropRef } = useDroppable({
    id,
    data: { kind },
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
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" className="text-[var(--text-tertiary)]">
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
