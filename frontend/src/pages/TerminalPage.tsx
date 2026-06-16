import { TerminalBenchCard, useEnvironmentSelection } from '../components';
import { PageShell } from '@design-system/layout';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();

  return (
    <PageShell>
      <div className="p-3">
        <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </div>
    </PageShell>
  );
}

export default TerminalPage;
