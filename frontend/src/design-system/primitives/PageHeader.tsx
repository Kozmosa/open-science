interface Props {
  eyebrow: string;
  title: string;
  description?: string;
}

function PageHeader({ eyebrow, title, description }: Props) {
  return (
    <section className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
        {eyebrow}
      </p>
      <h1
        className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
        style={{ fontFamily: 'var(--font-display)' }}
      >
        {title}
      </h1>
      {description ? (
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {description}
        </p>
      ) : null}
    </section>
  );
}

export default PageHeader;
