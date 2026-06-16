import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
}

export default function PageShell({ children, className = '' }: Props) {
  return (
    <div className={`flex min-h-0 w-full flex-1 flex-col overflow-y-auto border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-pane)] ${className}`}>
      {children}
    </div>
  );
}
