import { cva, type VariantProps } from 'class-variance-authority';
import type { ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

const alertVariants = cva(
  'rounded-lg border p-3 text-sm',
  {
    variants: {
      variant: {
        error: 'border-[var(--danger-border)] bg-[var(--danger-soft)] text-[var(--danger-foreground)]',
        warning: 'border-[var(--warning-border)] bg-[var(--warning-soft)] text-[var(--warning-foreground)]',
        success: 'border-[var(--success-border)] bg-[var(--success-soft)] text-[var(--success-foreground)]',
      },
    },
    defaultVariants: { variant: 'error' },
  }
);

interface Props extends VariantProps<typeof alertVariants> {
  children: ReactNode;
  className?: string;
}

export function Alert({ children, variant = 'error', className = '' }: Props) {
  return (
    <div className={cn(alertVariants({ variant }), className)}>
      {children}
    </div>
  );
}
