import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface Props extends SelectHTMLAttributes<HTMLSelectElement> {
  error?: string;
  children: ReactNode;
}

export const Select = forwardRef<HTMLSelectElement, Props>(function Select(
  { error, children, className = '', ...rest },
  ref
) {
  const errorClasses = error
    ? 'border-[var(--danger)] focus:border-[var(--danger)] focus:ring-[var(--danger)]/15'
    : 'border-[var(--border)] focus:border-[var(--apple-blue)] focus:ring-[var(--apple-blue)]/15';
  return (
    <select
      ref={ref}
      className={cn(
        'w-full rounded-lg bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition',
        errorClasses,
        'focus:ring-2',
        className
      )}
      {...rest}
    >
      {children}
    </select>
  );
});

