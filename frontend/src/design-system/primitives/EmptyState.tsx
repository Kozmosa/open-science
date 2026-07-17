import type { ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

interface EmptyStateProps {
  message: string;
  title?: string;
  icon?: ReactNode;
  actions?: ReactNode;
  variant?: 'dashed' | 'subtle';
  className?: string;
}

const variantClasses: Record<NonNullable<EmptyStateProps['variant']>, string> = {
  dashed: 'border border-dashed border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)]',
  subtle: 'bg-[var(--osci-color-surface-subtle)]',
};

export function EmptyState({ message, title, icon, actions, variant = 'dashed', className }: EmptyStateProps) {
  return (
    <div className={cn('flex min-h-40 flex-1 items-center justify-center rounded-[var(--osci-radius-md)] p-6', variantClasses[variant], className)}>
      <div className="max-w-md text-center">
        {icon ? <div className="mb-3 flex justify-center text-[var(--osci-color-text-muted)]">{icon}</div> : null}
        {title ? <h2 className="text-base font-semibold text-[var(--osci-color-text)]">{title}</h2> : null}
        <p className={cn('text-sm text-[var(--osci-color-text-muted)]', title && 'mt-1')}>{message}</p>
        {actions ? <div className="mt-4 flex justify-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
