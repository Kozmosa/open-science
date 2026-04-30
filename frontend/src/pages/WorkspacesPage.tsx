import { PageHeader } from '../components';
import { useT } from '../i18n';
import WorkspaceManagerCard from './workspaces/WorkspaceManagerCard';

function WorkspacesPage() {
  const t = useT();

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={t('pages.workspaces.eyebrow')}
        title={t('pages.workspaces.title')}
        description={t('pages.workspaces.description')}
      />

      <WorkspaceManagerCard />
    </div>
  );
}

export default WorkspacesPage;
