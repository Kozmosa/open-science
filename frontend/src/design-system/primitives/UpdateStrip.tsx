import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

type UpdateStripTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
const tones: Record<UpdateStripTone, string> = {
  neutral: 'border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] text-[var(--osci-color-text-secondary)]',
  info: 'border-[var(--osci-color-info-border)] bg-[var(--osci-color-info-soft)] text-[var(--osci-color-info-foreground)]',
  success: 'border-[var(--osci-color-success-border)] bg-[var(--osci-color-success-soft)] text-[var(--osci-color-success-foreground)]',
  warning: 'border-[var(--osci-color-warning-border)] bg-[var(--osci-color-warning-soft)] text-[var(--osci-color-warning-foreground)]',
  danger: 'border-[var(--osci-color-danger-border)] bg-[var(--osci-color-danger-soft)] text-[var(--osci-color-danger-foreground)]',
};

export function UpdateStrip({ tone = 'neutral', actions, className, children, ...props }: HTMLAttributes<HTMLDivElement> & { tone?: UpdateStripTone; actions?: ReactNode }) {
  return (
    <div role="status" className={cn('flex min-h-10 flex-wrap items-center justify-between gap-3 rounded-[var(--osci-radius-sm)] border px-3 py-2 text-sm', tones[tone], className)} {...props}>
      <div className="min-w-0">{children}</div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}
