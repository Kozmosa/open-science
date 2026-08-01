import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useEnvironmentSelection } from '@features/environments';
import TerminalBenchCard from '../components/TerminalBenchCard';
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
    <PageShell variant="canvas">
      <div className="mx-auto flex w-full max-w-[1450px] flex-col p-4 md:p-6">
        <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />
      </div>
    </PageShell>
  );
}

export default TerminalPage;
