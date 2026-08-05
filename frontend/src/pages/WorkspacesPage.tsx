import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import { WorkspacesPage as FeatureWorkspacesPage } from '@features/workspaces/pages';

export default function WorkspacesPage() {
  return (
    <FeatureWorkspacesPage
      renderTaskCreateFlow={(props) => <TaskCreateFlow {...props} source="workspace" />}
    />
  );
}
