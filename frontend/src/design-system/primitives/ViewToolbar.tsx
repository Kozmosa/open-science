import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

export function ViewToolbar({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div role="toolbar" className={cn('flex min-h-11 flex-wrap items-center gap-2 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3 py-2', className)} {...props} />;
}
