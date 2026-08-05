import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import { ProjectsPage as FeatureProjectsPage } from '@features/projects/pages';

export default function ProjectsPage() {
  return (
    <FeatureProjectsPage
      renderTaskCreateFlow={(props) => <TaskCreateFlow {...props} source="project" />}
    />
  );
}
