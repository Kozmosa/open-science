import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  variant?: 'default' | 'outline' | 'secondary';
  className?: string;
}

const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  default: 'rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--apple-blue)]',
  outline: 'rounded-full border border-[var(--border)] bg-transparent px-2 py-0.5 text-xs font-semibold text-[var(--text-secondary)]',
  secondary: 'rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-xs font-semibold text-[var(--text)]',
};

function Badge({ children, variant = 'default', className = '' }: Props) {
  return <span className={[variantClasses[variant], className].join(' ')}>{children}</span>;
}

export default Badge;
