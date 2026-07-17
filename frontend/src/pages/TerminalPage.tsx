import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useEnvironmentSelection } from '../components/environment';
import { TerminalBenchCard } from '../components/terminal';
import { PageShell } from '@design-system';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();
  const [searchParams] = useSearchParams();
  const routeEnvironmentId = searchParams.get('environment_id');

  useEffect(() => {
    if (routeEnvironmentId && routeEnvironmentId !== environmentSelection.selectedEnvironmentId) {
      environmentSelection.onSelectEnvironment(routeEnvironmentId);
    }
  }, [environmentSelection, routeEnvironmentId]);

  return (
    <PageShell>
      <div className="p-3">
        <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </div>
    </PageShell>
  );
}

export default TerminalPage;
