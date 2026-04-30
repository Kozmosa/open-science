interface Props {
  title: string;
  description?: string;
  eyebrow?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

function SectionHeader({ title, description, eyebrow, size = 'md', className = '' }: Props) {
  const titleClasses: Record<NonNullable<Props['size']>, string> = {
    sm: 'text-base font-semibold leading-tight tracking-[0.231px] text-[var(--text)]',
    md: 'text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]',
    lg: 'text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]',
  };
  return (
    <div className={['space-y-1', className].join(' ')}>
      {eyebrow ? (
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {eyebrow}
        </p>
      ) : null}
      <h2 className={titleClasses[size]} style={{ fontFamily: 'var(--font-display)' }}>
        {title}
      </h2>
      {description ? (
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {description}
        </p>
      ) : null}
    </div>
  );
}

export default SectionHeader;
