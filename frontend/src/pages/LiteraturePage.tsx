import { useState, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getLiteratureSubscriptions, getWorkspaces, createTask, convertPaperToTask } from '../api';
import { SplitPane, PageShell } from '../components/layout';
import { useT } from '../i18n';
import { useToast } from '../components/common/Toast';
import { useEnvironmentSelection } from '../components';
import SubscriptionSidebar from '../components/literature/SubscriptionSidebar';
import PaperFeed from '../components/literature/PaperFeed';
import ConvertToTaskDialog from '../components/literature/ConvertToTaskDialog';
import type { TaskCreatePayload } from '../types';

interface PendingConversion {
  paperId: string;
  subscriptionId: string;
  title: string;
  abstract: string;
}

export default function LiteraturePage() {
  const t = useT();
  const { showToast } = useToast();
  const environmentSelection = useEnvironmentSelection();
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<string | undefined>(undefined);
  const [pendingConversion, setPendingConversion] = useState<PendingConversion | null>(null);

  const subscriptionsQuery = useQuery({
    queryKey: ['literature-subscriptions'],
    queryFn: getLiteratureSubscriptions,
  });
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: getWorkspaces,
  });

  const subscriptions = subscriptionsQuery.data?.items ?? [];
  const workspaces = workspacesQuery.data?.items ?? [];
  const environments = environmentSelection.environments;

  const convertMutation = useMutation({
    mutationFn: async ({ paperId, subscriptionId, payload }: { paperId: string; subscriptionId: string; payload: TaskCreatePayload }) => {
      const task = await createTask(payload);
      await convertPaperToTask(paperId, task.task_id, subscriptionId);
      return task;
    },
    onSuccess: () => {
      showToast(t('literature.convertSuccess'), 'success');
      setPendingConversion(null);
    },
    onError: () => {
      showToast(t('literature.convertError'), 'error');
    },
  });

  const handleConvertToTask = useCallback((paperId: string, subscriptionId: string, title: string, abstract: string) => {
    setPendingConversion({ paperId, subscriptionId, title, abstract });
  }, []);

  const handleConfirmConversion = useCallback((payload: TaskCreatePayload) => {
    if (!pendingConversion) return;
    convertMutation.mutate({
      paperId: pendingConversion.paperId,
      subscriptionId: pendingConversion.subscriptionId,
      payload,
    });
  }, [pendingConversion, convertMutation]);

  return (
    <PageShell>
      {subscriptionsQuery.isLoading && (
        <p className="text-sm text-[var(--text-secondary)]">{t('common.loading')}</p>
      )}
      {!subscriptionsQuery.isLoading && (
        <SplitPane
          sidebar={
            <SubscriptionSidebar
              subscriptions={subscriptions}
              selectedSubscriptionId={selectedSubscriptionId}
              onSelectSubscription={setSelectedSubscriptionId}
            />
          }
          sidebarWidth={sidebarWidth}
          onSidebarWidthChange={setSidebarWidth}
          sidebarMinWidth={220}
          sidebarMaxWidth={400}
        >
          <PaperFeed
            subscriptions={subscriptions}
            selectedSubscriptionId={selectedSubscriptionId}
            onSubscriptionChange={setSelectedSubscriptionId}
            onConvertToTask={handleConvertToTask}
          />
        </SplitPane>
      )}

      <ConvertToTaskDialog
        isOpen={pendingConversion !== null}
        isSubmitting={convertMutation.isPending}
        paperTitle={pendingConversion?.title ?? ''}
        paperAbstract={pendingConversion?.abstract ?? ''}
        workspaces={workspaces}
        environments={environments}
        onConfirm={handleConfirmConversion}
        onCancel={() => setPendingConversion(null)}
      />
    </PageShell>
  );
}
