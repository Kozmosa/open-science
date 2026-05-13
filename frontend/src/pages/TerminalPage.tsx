import { TerminalBenchCard, useEnvironmentSelection } from '../components';

function TerminalPage() {
  const environmentSelection = useEnvironmentSelection();

  return <TerminalBenchCard selectedEnvironment={environmentSelection.selectedEnvironment} />;
}

export default TerminalPage;
