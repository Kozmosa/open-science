interface Props {
  status: 'success' | 'error' | 'warning' | 'idle';
  size?: 'sm' | 'md';
}

const statusColors: Record<Props['status'], string> = {
  success: 'bg-[#34c759]',
  error: 'bg-[#ff3b30]',
  warning: 'bg-[#ff9500]',
  idle: 'bg-[var(--text-tertiary)]',
};

const sizeClasses: Record<NonNullable<Props['size']>, string> = {
  sm: 'h-1.5 w-1.5',
  md: 'h-2 w-2',
};

function StatusDot({ status, size = 'md' }: Props) {
  return <span className={['inline-block rounded-full', statusColors[status], sizeClasses[size]].join(' ')} />;
}

export default StatusDot;
