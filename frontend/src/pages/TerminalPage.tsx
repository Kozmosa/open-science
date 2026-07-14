import { useEnvironmentSelection } from '../components/environment';
import { TerminalBenchCard } from '../components/terminal';
import { PageShell } from '@design-system';

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
