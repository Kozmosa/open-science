import { forwardRef, type InputHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { error, className, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={error ? true : rest['aria-invalid']}
      className={cn(
        'w-full rounded-[var(--osci-radius-sm)] border bg-[var(--osci-color-surface)] px-3 py-2.5 text-sm text-[var(--osci-color-text)] outline-none transition placeholder:text-[var(--osci-color-text-muted)] focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50',
        error
          ? 'border-[var(--osci-color-danger)] focus:border-[var(--osci-color-danger)] focus:ring-[var(--osci-color-danger-soft)]'
          : 'border-[var(--osci-color-border)] focus:border-[var(--osci-color-primary)] focus:ring-[var(--osci-color-primary-soft)]',
        className,
      )}
      {...rest}
    />
  );
});
