import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md';
  isLoading?: boolean;
  children: ReactNode;
}

const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  primary:
    'rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40',
  secondary:
    'rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:cursor-not-allowed disabled:opacity-40',
  danger:
    'rounded-lg bg-[#ff3b30] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#d32f2f] disabled:cursor-not-allowed disabled:opacity-40',
  ghost:
    'rounded-lg px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-40',
};

const sizeClasses: Record<NonNullable<Props['size']>, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: '',
};

const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', size = 'md', isLoading = false, children, className = '', disabled, ...rest },
  ref
) {
  const base = variantClasses[variant];
  const sizeOverride = size === 'sm' ? sizeClasses.sm : '';
  return (
    <button
      ref={ref}
      className={[base, size === 'sm' ? sizeOverride : '', className].join(' ')}
      disabled={disabled || isLoading}
      {...rest}
    >
      {isLoading ? 'Loading…' : children}
    </button>
  );
});

export default Button;
