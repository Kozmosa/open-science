import { useState, useCallback } from 'react';

export type CardKind = 'taskUsage' | 'system' | 'processes';

export interface CardLayout {
  cardOrder: CardKind[];
}

const defaultCardOrder: CardKind[] = ['taskUsage', 'system', 'processes'];

const defaultLayout: CardLayout = {
  cardOrder: defaultCardOrder,
};

function isCardKind(value: unknown): value is CardKind {
  return value === 'taskUsage' || value === 'system' || value === 'processes';
}

function normalizeCardOrder(value: unknown): CardKind[] | null {
  if (!Array.isArray(value) || !value.every(isCardKind)) {
    return null;
  }
  const seen = new Set<CardKind>();
  const order = value.filter((kind): kind is CardKind => {
    if (seen.has(kind)) return false;
    seen.add(kind);
    return true;
  });
  return [...order, ...defaultCardOrder.filter((kind) => !seen.has(kind))];
}

const storageKey = 'scholar-agent:resources-layout';

function readLayout(): CardLayout {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      const order = typeof parsed === 'object' && parsed !== null ? normalizeCardOrder((parsed as CardLayout).cardOrder) : null;
      if (order) {
        return { cardOrder: order };
      }
    }
  } catch {
    // ignore corrupted storage
  }
  return defaultLayout;
}

function writeLayout(layout: CardLayout): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(layout));
  } catch {
    // ignore storage failures
  }
}

export function useCardLayout() {
  const [layout, setLayoutState] = useState<CardLayout>(readLayout);

  const setLayout = useCallback((layout: CardLayout) => {
    setLayoutState(layout);
    writeLayout(layout);
  }, []);

  const swapCards = useCallback(
    (activeId: CardKind, overId: CardKind) => {
      const order = [...layout.cardOrder];
      const activeIndex = order.indexOf(activeId);
      const overIndex = order.indexOf(overId);
      if (activeIndex === -1 || overIndex === -1) return;
      const [removed] = order.splice(activeIndex, 1);
      order.splice(overIndex, 0, removed);
      setLayout({ cardOrder: order });
    },
    [layout, setLayout]
  );

  return { layout, setLayout, swapCards };
}
