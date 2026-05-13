import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  gap?: number;
  actions?: ReactNode;
  className?: string;
}

const GAP_CLASSES: Record<number, string> = { 2: 'space-y-2', 3: 'space-y-3', 4: 'space-y-4', 5: 'space-y-5', 6: 'space-y-6', 8: 'space-y-8' };
const MB_GAP_CLASSES: Record<number, string> = { 2: 'mb-2', 3: 'mb-3', 4: 'mb-4', 5: 'mb-5', 6: 'mb-6', 8: 'mb-8' };

export default function SectionStack({ children, gap = 6, actions, className = '' }: Props) {
  const gapClass = GAP_CLASSES[gap] ?? GAP_CLASSES[6];
  const mbClass = MB_GAP_CLASSES[gap] ?? MB_GAP_CLASSES[6];
  return (
    <div className={`${gapClass} ${className ?? ''}`}>
      {actions ? <div className={mbClass}>{actions}</div> : null}
      {children}
    </div>
  );
}
