import { FileBrowserPage as FeatureFileBrowserPage } from '@features/workspaces/pages/file-browser';
import { useEnvironmentSelectionPreferences } from '@features/settings';

export default function FileBrowserPage() {
  const preferences = useEnvironmentSelectionPreferences();
  return <FeatureFileBrowserPage preferences={preferences} />;
}
