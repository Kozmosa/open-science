import type { ReactNode } from 'react';

interface Props {
  label: string;
  error?: string;
  children: ReactNode;
}

export function FormField({ label, error, children }: Props) {
  return (
    <label className="space-y-2">
      <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">{label}</span>
      {children}
      {error ? <p className="text-xs text-[var(--danger)]">{error}</p> : null}
    </label>
  );
}

