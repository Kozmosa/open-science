import { TerminalBenchCard, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';

function TerminalPage() {
  const t = useT();
  const environmentSelection = useEnvironmentSelection();
  const description = t('pages.terminal.description');

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.terminal.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.terminal.title')}
        </h1>
        {description ? (
          <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
            {description}
          </p>
        ) : null}
      </section>

      <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </div>
  );
}

export default TerminalPage;
