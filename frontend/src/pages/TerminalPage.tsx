import { TerminalPage as FeatureTerminalPage } from '@features/terminal/pages';
import { useEnvironmentSelectionPreferences } from '@features/settings';

export default function TerminalPage() {
  const preferences = useEnvironmentSelectionPreferences();
  return <FeatureTerminalPage preferences={preferences} />;
}
