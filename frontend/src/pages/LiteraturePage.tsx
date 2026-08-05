import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import { LiteraturePage as FeatureLiteraturePage } from '@features/literature/pages';

export default function LiteraturePage() {
  return (
    <FeatureLiteraturePage
      renderTaskCreateFlow={(props) => <TaskCreateFlow {...props} source="literature" />}
    />
  );
}
