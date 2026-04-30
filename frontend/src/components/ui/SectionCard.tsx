import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  className?: string;
}

function SectionCard({ children, className = '' }: Props) {
  return (
    <section className={['space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm', className].join(' ')}>
      {children}
    </section>
  );
}

export default SectionCard;
