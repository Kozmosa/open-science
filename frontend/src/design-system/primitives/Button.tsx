import { useT } from '@/shared/i18n';
import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

const buttonVariants = cva(
  'inline-flex items-center justify-center rounded-lg text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      variant: {
        primary:
          'bg-[var(--apple-blue)] text-white hover:bg-[var(--apple-blue-hover)]',
        secondary:
          'border border-[var(--border)] bg-[var(--bg)] text-[var(--text)] hover:bg-[var(--bg-secondary)]',
        danger:
          'bg-[var(--danger)] text-[var(--destructive-foreground)] hover:opacity-90',
        ghost:
          'text-[var(--muted-foreground)] hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]',
      },
      size: {
        sm: 'px-3 py-1.5 text-xs',
        md: 'px-4 py-2',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  }
);

interface Props
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = 'primary',
    size = 'md',
    isLoading = false,
    children,
    className = '',
    disabled,
    ...rest
  },
  ref
) {
  const t = useT();
  return (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || isLoading}
      {...rest}
    >
      {isLoading ? t('common.loading') : children}
    </button>
  );
});

