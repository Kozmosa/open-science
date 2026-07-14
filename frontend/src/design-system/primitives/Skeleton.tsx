import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('animate-pulse rounded-[var(--osci-radius-sm)] bg-[var(--osci-color-surface-subtle)]', className)} {...props} />;
}
