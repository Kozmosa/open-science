import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
}

export default function PageShell({ children, className = '' }: Props) {
  return (
    <div className={`flex min-h-0 flex-1 bg-[var(--bg)] p-4 ${className}`}>
      <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        {children}
      </div>
    </div>
  );
}
