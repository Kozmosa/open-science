import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  variant?: 'error' | 'warning' | 'success';
  className?: string;
}

const variantClasses: Record<NonNullable<Props['variant']>, string> = {
  error: 'border-[#ff3b30]/20 bg-[#ffebee] text-[#c62828]',
  warning: 'border-[#ff9500]/20 bg-[#fff3e0] text-[#e65100]',
  success: 'border-[#34c759]/20 bg-[#e8f5e9] text-[#2e7d32]',
};

function Alert({ children, variant = 'error', className = '' }: Props) {
  return (
    <div className={['rounded-lg border p-3 text-sm', variantClasses[variant], className].join(' ')}>
      {children}
    </div>
  );
}

export default Alert;
