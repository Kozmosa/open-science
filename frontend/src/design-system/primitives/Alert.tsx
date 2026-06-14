import type { ReactNode } from 'react';
import { semanticToneClasses } from '@design-system/tokens/theme';

interface Props {
  children: ReactNode;
  variant?: 'error' | 'warning' | 'success';
  className?: string;
}

const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  error: semanticToneClasses.danger,
  warning: semanticToneClasses.warning,
  success: semanticToneClasses.success,
};

function Alert({ children, variant = 'error', className = '' }: Props) {
  return (
    <div className={['rounded-lg border p-3 text-sm', variantClasses[variant], className].join(' ')}>
      {children}
    </div>
  );
}

export default Alert;
