import type { ReactNode } from 'react';

interface Props {
  message: string;
  icon?: ReactNode;
  variant?: 'dashed' | 'subtle';
}

const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  dashed: 'rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)]',
  subtle: 'rounded-lg bg-[var(--bg-secondary)]',
};

function EmptyState({ message, icon, variant = 'dashed' }: Props) {
  return (
    <div className={['flex flex-1 items-center justify-center', variantClasses[variant]].join(' ')}>
      <div className="text-center">
        {icon ? <div className="mb-2 flex justify-center text-[var(--text-tertiary)]">{icon}</div> : null}
        <p className="text-sm text-[var(--text-tertiary)]">{message}</p>
      </div>
    </div>
  );
}

export default EmptyState;
