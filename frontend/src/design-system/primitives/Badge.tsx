import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

const badgeVariants = cva('inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold', {
  variants: {
    variant: {
      default: 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)] text-[var(--osci-color-primary)]',
      outline: 'border-[var(--osci-color-border)] bg-transparent text-[var(--osci-color-text-muted)]',
      secondary: 'border-transparent bg-[var(--osci-color-surface-subtle)] text-[var(--osci-color-text)]',
      success: 'border-[var(--osci-color-success-border)] bg-[var(--osci-color-success-soft)] text-[var(--osci-color-success-foreground)]',
      warning: 'border-[var(--osci-color-warning-border)] bg-[var(--osci-color-warning-soft)] text-[var(--osci-color-warning-foreground)]',
      danger: 'border-[var(--osci-color-danger-border)] bg-[var(--osci-color-danger-soft)] text-[var(--osci-color-danger-foreground)]',
    },
  },
  defaultVariants: { variant: 'default' },
});

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ variant = 'default', className, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export type StatusBadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export function StatusBadge({ tone = 'neutral', ...props }: Omit<BadgeProps, 'variant'> & { tone?: StatusBadgeTone }) {
  const variants: Record<StatusBadgeTone, BadgeProps['variant']> = {
    neutral: 'secondary',
    info: 'default',
    success: 'success',
    warning: 'warning',
    danger: 'danger',
  };
  return <Badge variant={variants[tone]} {...props} />;
}
