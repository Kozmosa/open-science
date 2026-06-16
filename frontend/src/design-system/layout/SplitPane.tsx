import { useCallback, useRef, type ReactNode } from 'react';
import { useT } from '@/shared/i18n';

interface SplitPaneProps {
  sidebar: ReactNode;
  children: ReactNode;
  sidebarWidth: number;
  onSidebarWidthChange: (width: number) => void;
  sidebarMinWidth?: number;
  sidebarMaxWidth?: number;
  rightSidebar?: ReactNode;
  rightSidebarWidth?: number;
  onRightSidebarWidthChange?: (width: number) => void;
  rightSidebarMinWidth?: number;
  rightSidebarMaxWidth?: number;
  className?: string;
  sidebarTestId?: string;
  rightSidebarTestId?: string;
}

function clampWidth(width: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, width));
}

function ResizeHandle({
  width,
  minWidth,
  maxWidth,
  onWidthChange,
  isRight,
  ariaLabel,
}: {
  width: number;
  minWidth: number;
  maxWidth: number;
  onWidthChange: (width: number) => void;
  isRight?: boolean;
  ariaLabel?: string;
}) {
  const startRef = useRef({ x: 0, width: 0 });

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      startRef.current = { x: event.clientX, width };

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const delta = moveEvent.clientX - startRef.current.x;
        const newWidth = isRight
          ? startRef.current.width - delta
          : startRef.current.width + delta;
        onWidthChange(clampWidth(newWidth, minWidth, maxWidth));
      };

      const handlePointerUp = () => {
        window.removeEventListener('pointermove', handlePointerMove);
        window.removeEventListener('pointerup', handlePointerUp);
      };

      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    },
    [width, minWidth, maxWidth, onWidthChange, isRight]
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      event.preventDefault();
      const delta = event.key === 'ArrowLeft' ? -16 : 16;
      // For the right handle, arrow directions are inverted relative to width.
      const effectiveDelta = isRight ? -delta : delta;
      onWidthChange(clampWidth(width + effectiveDelta, minWidth, maxWidth));
    },
    [width, minWidth, maxWidth, onWidthChange, isRight]
  );

  return (
    <div
      className="group flex w-2 shrink-0 cursor-col-resize items-center justify-center bg-[var(--surface)] transition-colors hover:bg-[var(--surface-hover)]"
      role="separator"
      aria-orientation="vertical"
      aria-label={ariaLabel}
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
    >
      <div className="h-8 w-0.5 rounded-full bg-[var(--border)] transition-colors group-hover:bg-[var(--apple-blue)] group-focus-visible:bg-[var(--apple-blue)]" />
    </div>
  );
}

export default function SplitPane({
  sidebar,
  children,
  sidebarWidth,
  onSidebarWidthChange,
  sidebarMinWidth = 260,
  sidebarMaxWidth = 520,
  rightSidebar,
  rightSidebarWidth = 320,
  onRightSidebarWidthChange,
  rightSidebarMinWidth = 260,
  rightSidebarMaxWidth = 520,
  className,
  sidebarTestId,
  rightSidebarTestId,
}: SplitPaneProps) {
  const t = useT();

  const leftCollapsed = sidebarWidth <= 0;
  const rightCollapsed = (rightSidebarWidth ?? 0) <= 0;

  return (
    <div className={`flex min-h-0 w-full flex-1 ${className ?? ''}`}>
      {!leftCollapsed && (
        <aside
          className="flex shrink-0 flex-col overflow-hidden bg-[var(--sidebar)] relative z-0"
          style={{ width: sidebarWidth }}
          data-testid={sidebarTestId}
        >
          <div className="flex min-h-0 flex-1 flex-col [&>*:last-child]:min-h-0 [&>*:last-child]:flex-1">
            {sidebar}
          </div>
        </aside>
      )}

      {!leftCollapsed && (
        <ResizeHandle
          width={sidebarWidth}
          minWidth={sidebarMinWidth}
          maxWidth={sidebarMaxWidth}
          onWidthChange={onSidebarWidthChange}
          ariaLabel={t('layout.resizeSidebar')}
        />
      )}

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-[var(--bg)] p-3 relative z-10">
        <div className="flex min-h-0 flex-1 flex-col [&>*]:min-h-0 [&>*]:flex-1">
          {children}
        </div>
      </main>

      {rightSidebar && !rightCollapsed && (
        <ResizeHandle
          width={rightSidebarWidth}
          minWidth={rightSidebarMinWidth}
          maxWidth={rightSidebarMaxWidth}
          onWidthChange={onRightSidebarWidthChange ?? (() => {})}
          isRight
          ariaLabel={t('layout.resizeSidebar')}
        />
      )}

      {rightSidebar && !rightCollapsed && (
        <aside
          className="flex shrink-0 flex-col overflow-hidden bg-[var(--sidebar)] p-3 relative z-0"
          style={{ width: rightSidebarWidth }}
          data-testid={rightSidebarTestId}
        >
          <div className="flex min-h-0 flex-1 flex-col [&>*:last-child]:min-h-0 [&>*:last-child]:flex-1">
            {rightSidebar}
          </div>
        </aside>
      )}
    </div>
  );
}
