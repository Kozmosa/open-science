import { TerminalBenchCard, useEnvironmentSelection } from '../components';
import { PageShell } from '../components/layout';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();

  return (
    <PageShell>
      <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
    </PageShell>
  );
}

export default TerminalPage;
