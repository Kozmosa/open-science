interface Props {
  eyebrow: string;
  title: string;
  description: string;
  badgeLabel: string;
}

function PlaceholderPage({ eyebrow, title, description, badgeLabel }: Props) {
  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 shadow-sm">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">{eyebrow}</p>
        <h1 className="mt-3 text-3xl font-semibold text-[var(--text)]">{title}</h1>
        <p className="mt-3 max-w-2xl text-sm text-[var(--text-secondary)] sm:text-base">{description}</p>
        <div className="mt-6 inline-flex rounded-full border border-[var(--accent)]/20 bg-[var(--accent)]/10 px-3 py-1 text-sm font-medium text-[var(--accent)]">
          {badgeLabel}
        </div>
      </section>
    </div>
  );
}

export default PlaceholderPage;
