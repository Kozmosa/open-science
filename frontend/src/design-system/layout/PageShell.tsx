import type { ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

interface PageShellProps {
  children: ReactNode;
  className?: string;
  variant?: 'legacy' | 'canvas';
}

export default function PageShell({ children, className, variant = 'legacy' }: PageShellProps) {
  return (
    <div
      data-page-shell-variant={variant}
      className={cn(
        'flex min-h-0 w-full flex-1 flex-col overflow-y-auto',
        variant === 'legacy'
          ? 'border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] shadow-[var(--osci-shadow-md)]'
          : 'bg-[var(--osci-color-canvas)]',
        className,
      )}
    >
      {children}
    </div>
  );
}
