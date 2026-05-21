import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getLiteratureSubscriptions } from '../api';
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

  const handleConvertToTask = (_paperId: string) => {
    // Placeholder: task conversion will use the task creation flow
    // PaperCard button is disabled when already converted
  };

  return (
    <PageShell>
      <div className="space-y-6 p-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-tertiary)]">
            {t('nav.literature')}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{t('nav.literature')}</h1>
        </div>

        {subscriptionsQuery.isLoading && (
          <p className="text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
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
      </div>
    </PageShell>
  );
}
