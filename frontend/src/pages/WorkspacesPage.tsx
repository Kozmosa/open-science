import { CodeServerCard, EnvironmentSelectorPanel, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';

function WorkspacesPage() {
  const t = useT();
  const environmentSelection = useEnvironmentSelection();

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.workspaces.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.workspaces.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.workspaces.description')}
        </p>
      </section>

      <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
        <EnvironmentSelectorPanel {...environmentSelection} />
        <CodeServerCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </section>
    </div>
  );
}

export default WorkspacesPage;
