import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { error, className = '', ...rest },
  ref
) {
  const errorClasses = error
    ? 'border-[var(--danger)] focus:border-[var(--danger)] focus:ring-[var(--danger)]/15'
    : 'border-[var(--border)] focus:border-[var(--apple-blue)] focus:ring-[var(--apple-blue)]/15';
  return (
    <input
      ref={ref}
      className={cn(
        'w-full rounded-lg border bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition',
        errorClasses,
        'focus:ring-2',
        className
      )}
      {...rest}
    />
  );
});

