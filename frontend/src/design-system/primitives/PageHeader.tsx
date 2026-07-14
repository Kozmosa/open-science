import type { ReactNode } from 'react';

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-2">
        {eyebrow ? <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--osci-color-primary)]">{eyebrow}</p> : null}
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight text-[var(--osci-color-text)]">{title}</h1>
        {description ? <p className="max-w-3xl text-sm leading-relaxed text-[var(--osci-color-text-secondary)]">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
