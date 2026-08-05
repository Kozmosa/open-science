import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useEnvironmentSelection, type EnvironmentSelectionPreferences } from '@features/environments';
import TerminalBenchCard from '../components/TerminalBenchCard';
import { PageShell } from '@design-system';

export interface TerminalPageProps {
  preferences: EnvironmentSelectionPreferences;
}

function TerminalPage({ preferences }: TerminalPageProps) {
  const environmentSelection = useEnvironmentSelection(undefined, preferences);
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
