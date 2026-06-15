import { cva, type VariantProps } from 'class-variance-authority';
import type { ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

const badgeVariants = cva(
  'rounded-full px-2 py-0.5 text-xs font-semibold',
  {
    variants: {
      variant: {
        default: 'bg-[var(--apple-blue)]/10 text-[var(--apple-blue)]',
        outline: 'border border-[var(--border)] bg-transparent text-[var(--text-secondary)]',
        secondary: 'bg-[var(--bg-secondary)] text-[var(--text)]',
      },
    },
    defaultVariants: { variant: 'default' },
  }
);

interface Props extends VariantProps<typeof badgeVariants> {
  children: ReactNode;
  className?: string;
}

export function Badge({ children, variant = 'default', className = '' }: Props) {
  return <span className={cn(badgeVariants({ variant }), className)}>{children}</span>;
}
