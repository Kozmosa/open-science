import { semanticDotClasses } from '@design-system/tokens/theme';

interface Props {
  status: 'success' | 'error' | 'warning' | 'idle';
  size?: 'sm' | 'md';
}

const statusColors: Record<Props['status'], string> = {
  success: semanticDotClasses.success,
  error: semanticDotClasses.danger,
  warning: semanticDotClasses.warning,
  idle: semanticDotClasses.muted,
};

const sizeClasses: Record<NonNullable<Props['size']>, string> = {
  sm: 'h-1.5 w-1.5',
  md: 'h-2 w-2',
};

export function StatusDot({ status, size = 'md' }: Props) {
  return <span className={['inline-block rounded-full', statusColors[status], sizeClasses[size]].join(' ')} />;
}

