import type { ReactNode } from 'react';

interface SectionStackProps {
  children: ReactNode;
  gap?: number;
  actions?: ReactNode;
  className?: string;
}

export default function SectionStack({ children, gap = 6, actions, className }: SectionStackProps) {
  if (actions) {
    return (
      <div className={`space-y-${gap} ${className ?? ''}`}>
        <div className={`mb-${gap}`}>{actions}</div>
        {children}
      </div>
    );
  }

  return <div className={`space-y-${gap} ${className ?? ''}`}>{children}</div>;
}
