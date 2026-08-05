import { EnvironmentsPage as FeatureEnvironmentsPage } from '@features/environments/pages';
import { useEnvironmentSelectionPreferences } from '@features/settings';

export default function EnvironmentsPage() {
  const preferences = useEnvironmentSelectionPreferences();
  return <FeatureEnvironmentsPage preferences={preferences} />;
}
