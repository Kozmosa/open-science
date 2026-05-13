import { useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { useT } from '../../i18n';

interface SplitPaneProps {
  sidebar: ReactNode;
  children: ReactNode;
  sidebarWidth: number;
  onSidebarWidthChange: (width: number) => void;
  sidebarMinWidth?: number;
  sidebarMaxWidth?: number;
  className?: string;
}

function clampWidth(width: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, width));
}

export default function SplitPane({
  sidebar,
  children,
  sidebarWidth,
  onSidebarWidthChange,
  sidebarMinWidth = 260,
  sidebarMaxWidth = 520,
  className,
}: SplitPaneProps) {
  const t = useT();
  const startRef = useRef({ x: 0, width: 0 });

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      startRef.current = { x: event.clientX, width: sidebarWidth };

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const newWidth = clampWidth(
          startRef.current.width + moveEvent.clientX - startRef.current.x,
          sidebarMinWidth,
          sidebarMaxWidth
        );
        onSidebarWidthChange(newWidth);
      };

      const handlePointerUp = () => {
        window.removeEventListener('pointermove', handlePointerMove);
        window.removeEventListener('pointerup', handlePointerUp);
      };

      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    },
    [sidebarWidth, sidebarMinWidth, sidebarMaxWidth, onSidebarWidthChange]
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const delta = event.key === 'ArrowLeft' ? -16 : 16;
      onSidebarWidthChange(clampWidth(sidebarWidth + delta, sidebarMinWidth, sidebarMaxWidth));
    },
    [sidebarWidth, sidebarMinWidth, sidebarMaxWidth, onSidebarWidthChange]
  );

  return (
    <div className={`flex min-h-0 flex-1 bg-[var(--bg)] p-4 ${className ?? ''}`}>
      <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <aside
          className="flex shrink-0 flex-col bg-[var(--sidebar)] p-3"
          style={{ width: sidebarWidth }}
        >
          {sidebar}
        </aside>

        <div
          className="group flex w-2 shrink-0 cursor-col-resize items-center justify-center bg-[var(--surface)] transition-colors hover:bg-[var(--surface-hover)]"
          role="separator"
          aria-orientation="vertical"
          aria-label={t('layout.resizeSidebar')}
          aria-valuemin={sidebarMinWidth}
          aria-valuemax={sidebarMaxWidth}
          aria-valuenow={sidebarWidth}
          tabIndex={0}
          onPointerDown={handlePointerDown}
          onKeyDown={handleKeyDown}
        >
          <div className="h-8 w-0.5 rounded-full bg-[var(--border)] transition-colors group-hover:bg-[var(--apple-blue)] group-focus-visible:bg-[var(--apple-blue)]" />
        </div>

        <main className="flex min-w-0 flex-1 flex-col bg-[var(--bg)] p-4">
          {children}
        </main>
      </div>
    </div>
  );
}
