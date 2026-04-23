interface Props {
  size?: 'sm' | 'md' | 'lg';
  message?: string;
}

function LoadingSpinner({ size = 'md', message }: Props) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-10 h-10',
  };

  return (
    <div className="flex flex-col items-center justify-center gap-2">
      <div
        className={`${sizeClasses[size]} rounded-full border-2 border-[var(--border)] border-t-[var(--apple-blue)] animate-spin`}
      />
      {message && (
        <span className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {message}
        </span>
      )}
    </div>
  );
}

export default LoadingSpinner;
