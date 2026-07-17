import { useCallback, useEffect, useRef } from 'react';
import { useUserPreference } from '@/shared/hooks/useUserPreference';

export type CardKind = 'taskUsage' | 'system' | 'processes';
export interface CardLayout { cardOrder: CardKind[] }

const defaultCardOrder: CardKind[] = ['taskUsage', 'system', 'processes'];
const defaultLayout: CardLayout = { cardOrder: defaultCardOrder };
const legacyStorageKeys = ['openscience:resources-layout', 'scholar-agent:resources-layout'];

function isCardKind(value: unknown): value is CardKind {
  return value === 'taskUsage' || value === 'system' || value === 'processes';
}

function normalizeCardOrder(value: unknown): CardKind[] | null {
  if (!Array.isArray(value) || !value.every(isCardKind)) return null;
  const seen = new Set<CardKind>();
  const order = value.filter((kind) => {
    if (seen.has(kind)) return false;
    seen.add(kind);
    return true;
  });
  return [...order, ...defaultCardOrder.filter((kind) => !seen.has(kind))];
}

function isCardLayout(value: unknown): value is CardLayout {
  if (typeof value !== 'object' || value === null) return false;
  return normalizeCardOrder((value as CardLayout).cardOrder) !== null;
}

export function useCardLayout(userId: string) {
  const [layout, setStoredLayout] = useUserPreference<CardLayout>(
    userId,
    'resources-card-layout',
    defaultLayout,
    isCardLayout,
  );
  const migratedRef = useRef(false);
  useEffect(() => {
    if (migratedRef.current) return;
    migratedRef.current = true;
    try {
      for (const key of legacyStorageKeys) {
        const raw = window.localStorage.getItem(key);
        if (raw === null) continue;
        const parsed: unknown = JSON.parse(raw);
        const order = typeof parsed === 'object' && parsed !== null
          ? normalizeCardOrder((parsed as CardLayout).cardOrder)
          : null;
        if (order) setStoredLayout({ cardOrder: order });
        window.localStorage.removeItem(key);
        break;
      }
    } catch {
      // Corrupt legacy preferences are ignored and left for manual cleanup.
    }
  }, [setStoredLayout]);

  const setLayout = useCallback((next: CardLayout) => {
    setStoredLayout({ cardOrder: normalizeCardOrder(next.cardOrder) ?? defaultCardOrder });
  }, [setStoredLayout]);

  const swapCards = useCallback((activeId: CardKind, overId: CardKind) => {
    const order = [...layout.cardOrder];
    const activeIndex = order.indexOf(activeId);
    const overIndex = order.indexOf(overId);
    if (activeIndex < 0 || overIndex < 0) return;
    const [removed] = order.splice(activeIndex, 1);
    order.splice(overIndex, 0, removed);
    setLayout({ cardOrder: order });
  }, [layout.cardOrder, setLayout]);

  return { layout, setLayout, swapCards };
}
