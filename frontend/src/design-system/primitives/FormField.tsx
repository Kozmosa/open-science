import { forwardRef, useId, type FormHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

export const Form = forwardRef<HTMLFormElement, FormHTMLAttributes<HTMLFormElement>>(function Form(
  { className, ...props },
  ref,
) {
  return <form ref={ref} className={cn('space-y-4', className)} {...props} />;
});

interface FormFieldProps {
  label: string;
  error?: string;
  description?: string;
  required?: boolean;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}

export function FormField({ label, error, description, required = false, htmlFor, children, className }: FormFieldProps) {
  const generatedId = useId();
  const descriptionId = description ? `${generatedId}-description` : undefined;
  const errorId = error ? `${generatedId}-error` : undefined;
  return (
    <label htmlFor={htmlFor} className={cn('block space-y-2', className)}>
      <span className="text-sm font-medium text-[var(--osci-color-text)]">
        {label}{required ? <span aria-hidden="true" className="text-[var(--osci-color-danger)]"> *</span> : null}
      </span>
      {children}
      {description ? <p id={descriptionId} className="text-xs text-[var(--osci-color-text-muted)]">{description}</p> : null}
      {error ? <p id={errorId} role="alert" className="text-xs text-[var(--osci-color-danger)]">{error}</p> : null}
    </label>
  );
}
