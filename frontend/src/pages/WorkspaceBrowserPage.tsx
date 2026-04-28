import { CodeServerCard, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';

function WorkspaceBrowserPage() {
  const t = useT();
  const environmentSelection = useEnvironmentSelection();

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.workspaceBrowser.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.workspaceBrowser.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.workspaceBrowser.description')}
        </p>
      </section>

      <CodeServerCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </div>
  );
}

export default WorkspaceBrowserPage;
