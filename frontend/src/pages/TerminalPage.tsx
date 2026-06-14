import { TerminalBenchCard, useEnvironmentSelection } from '../components';
import { PageShell } from '@design-system/layout';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();

  return (
    <PageShell>
      <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </PageShell>
  );
}

export default TerminalPage;
