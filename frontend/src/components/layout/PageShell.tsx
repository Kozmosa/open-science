import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
}

export default function PageShell({ children, className = '' }: Props) {
  return (
    <div className={`flex min-h-0 w-full flex-1 flex-col overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-pane)] ${className}`}>
      {children}
    </div>
  );
}
