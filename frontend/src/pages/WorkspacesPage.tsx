import { PageHeader } from '../components';
import { SectionStack } from '../components/layout';
import { useT } from '../i18n';
import WorkspaceManagerCard from './workspaces/WorkspaceManagerCard';

function WorkspacesPage() {
  const t = useT();

  return (
    <SectionStack gap={8}>
      <PageHeader
        eyebrow={t('pages.workspaces.eyebrow')}
        title={t('pages.workspaces.title')}
        description={t('pages.workspaces.description')}
      />

      <WorkspaceManagerCard />
    </SectionStack>
  );
}

export default WorkspacesPage;
