import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

const alertVariants = cva('rounded-[var(--osci-radius-sm)] border p-3 text-sm', {
  variants: {
    variant: {
      error: 'border-[var(--osci-color-danger-border)] bg-[var(--osci-color-danger-soft)] text-[var(--osci-color-danger-foreground)]',
      warning: 'border-[var(--osci-color-warning-border)] bg-[var(--osci-color-warning-soft)] text-[var(--osci-color-warning-foreground)]',
      success: 'border-[var(--osci-color-success-border)] bg-[var(--osci-color-success-soft)] text-[var(--osci-color-success-foreground)]',
      info: 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)] text-[var(--osci-color-text)]',
    },
  },
  defaultVariants: { variant: 'error' },
});

export interface AlertProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof alertVariants> {}

export function Alert({ variant = 'error', className, role, ...props }: AlertProps) {
  return <div role={role ?? (variant === 'error' ? 'alert' : 'status')} className={cn(alertVariants({ variant }), className)} {...props} />;
}
