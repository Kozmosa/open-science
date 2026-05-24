import { useState, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getLiteratureSubscriptions, createTask, convertPaperToTask } from '../api';
import { SplitPane, PageShell } from '../components/layout';
import { useT } from '../i18n';
import SubscriptionSidebar from '../components/literature/SubscriptionSidebar';
import PaperFeed from '../components/literature/PaperFeed';

export default function LiteraturePage() {
  const t = useT();
  const [sidebarWidth, setSidebarWidth] = useState(280);

  const subscriptionsQuery = useQuery({
    queryKey: ['literature-subscriptions'],
    queryFn: getLiteratureSubscriptions,
  });

  const subscriptions = subscriptionsQuery.data?.items ?? [];

  const convertMutation = useMutation({
    mutationFn: async ({ paperId, subscriptionId, title, abstract }: { paperId: string; subscriptionId: string; title: string; abstract: string }) => {
      const task = await createTask({
        project_id: 'default',
        workspace_id: 'workspace-default',
        environment_id: 'env-localhost',
        task_profile: 'claude-code',
        title: title.slice(0, 200),
        task_input: abstract,
        execution_engine: 'claude-code',
      });
      await convertPaperToTask(paperId, task.task_id, subscriptionId);
      return task;
    },
  });

  const handleConvertToTask = useCallback((paperId: string, subscriptionId: string, title: string, abstract: string) => {
    convertMutation.mutate({ paperId, subscriptionId, title, abstract });
  }, [convertMutation]);

  return (
    <PageShell>
      {subscriptionsQuery.isLoading && (
        <p className="text-sm text-[var(--text-secondary)]">{t('common.loading')}</p>
      )}
      {!subscriptionsQuery.isLoading && (
        <SplitPane
          sidebar={<SubscriptionSidebar subscriptions={subscriptions} />}
          sidebarWidth={sidebarWidth}
          onSidebarWidthChange={setSidebarWidth}
          sidebarMinWidth={220}
          sidebarMaxWidth={400}
        >
          <PaperFeed
            subscriptions={subscriptions}
            onConvertToTask={handleConvertToTask}
          />
        </SplitPane>
      )}
    </PageShell>
  );
}
