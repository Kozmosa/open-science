import { PageHeader, TerminalBenchCard, useEnvironmentSelection } from '../components';
import { useT } from '../i18n';

function TerminalPage() {
  const t = useT();
  const environmentSelection = useEnvironmentSelection();

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={t('pages.terminal.eyebrow')}
        title={t('pages.terminal.title')}
        description={t('pages.terminal.description')}
      />

      <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </div>
  );
}

export default TerminalPage;
