import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

interface NativeSelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  error?: string;
  children: ReactNode;
}

export const NativeSelect = forwardRef<HTMLSelectElement, NativeSelectProps>(function NativeSelect(
  { error, children, className, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      aria-invalid={error ? true : rest['aria-invalid']}
      className={cn(
        'w-full rounded-[var(--osci-radius-sm)] border bg-[var(--osci-color-surface)] px-3 py-2.5 text-sm text-[var(--osci-color-text)] outline-none transition focus:ring-2',
        error
          ? 'border-[var(--osci-color-danger)] focus:border-[var(--osci-color-danger)] focus:ring-[var(--osci-color-danger-soft)]'
          : 'border-[var(--osci-color-border)] focus:border-[var(--osci-color-primary)] focus:ring-[var(--osci-color-primary-soft)]',
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  );
});
