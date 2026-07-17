import { useT } from '@/shared/i18n';
import { cva, type VariantProps } from 'class-variance-authority';
import { LoaderCircle } from 'lucide-react';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

const buttonVariants = cva(
  'relative inline-flex items-center justify-center rounded-[var(--osci-radius-sm)] text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--osci-color-primary-soft)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--osci-color-canvas)] disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      variant: {
        primary: 'bg-[var(--osci-color-primary)] text-[var(--osci-color-on-accent)] hover:bg-[var(--osci-color-primary-hover)]',
        secondary: 'border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] text-[var(--osci-color-text)] hover:bg-[var(--osci-color-surface-subtle)]',
        danger: 'bg-[var(--osci-color-danger)] text-[var(--osci-color-on-accent)] hover:opacity-90',
        ghost: 'text-[var(--osci-color-text-muted)] hover:bg-[var(--osci-color-surface-subtle)] hover:text-[var(--osci-color-text)]',
      },
      size: {
        sm: 'min-h-8 px-3 py-1.5 text-xs',
        md: 'min-h-10 px-4 py-2',
        lg: 'min-h-11 px-5 py-2.5',
        icon: 'h-10 w-10 p-0',
        'icon-sm': 'h-8 w-8 p-0',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
);

type ButtonSize = NonNullable<VariantProps<typeof buttonVariants>['size']>;
type BaseButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  Omit<VariantProps<typeof buttonVariants>, 'size'> & {
    isLoading?: boolean;
    children: ReactNode;
  };
type IconButtonProps = BaseButtonProps & {
  size: Extract<ButtonSize, 'icon' | 'icon-sm'>;
  'aria-label': string;
};
type TextButtonProps = BaseButtonProps & {
  size?: Exclude<ButtonSize, 'icon' | 'icon-sm'>;
};
export type ButtonProps = IconButtonProps | TextButtonProps;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', isLoading = false, children, className, disabled, ...rest },
  ref,
) {
  const t = useT();
  return (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      {...rest}
    >
      {isLoading ? <span className="invisible inline-flex items-center justify-center">{children}</span> : children}
      {isLoading ? (
        <span className="absolute inset-0 inline-flex items-center justify-center" aria-label={t('common.loading')}>
          <LoaderCircle aria-hidden="true" className="animate-spin" size={16} />
        </span>
      ) : null}
    </button>
  );
});
