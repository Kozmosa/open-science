import TerminalBenchCardView from './TerminalBenchCardView';
import { useTerminalBenchSession } from './useTerminalBenchSession';
import type { EnvironmentRecord } from '../../types';

interface Props {
  selectedEnvironment: EnvironmentRecord | null;
}

function TerminalBenchCard({ selectedEnvironment }: Props) {
  const state = useTerminalBenchSession(selectedEnvironment);

  return (
    <TerminalBenchCardView
      {...state}
      selectedEnvironmentSummary={
        selectedEnvironment ? `${selectedEnvironment.alias} · ${selectedEnvironment.display_name}` : null
      }
    />
  );
}

export default TerminalBenchCard;
