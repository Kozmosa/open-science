import { useState, useCallback } from 'react';

export type CardKind = 'system' | 'processes';

export interface CardLayout {
  cardOrder: CardKind[];
}

const defaultLayout: CardLayout = {
  cardOrder: ['system', 'processes'],
};

const storageKey = 'scholar-agent:resources-layout';

function readLayout(): CardLayout {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (raw) {
      const parsed = JSON.parse(raw) as unknown;
      if (
        typeof parsed === 'object' &&
        parsed !== null &&
        Array.isArray((parsed as CardLayout).cardOrder) &&
        (parsed as CardLayout).cardOrder.every(
          (k): k is CardKind => k === 'system' || k === 'processes'
        )
      ) {
        return parsed as CardLayout;
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
