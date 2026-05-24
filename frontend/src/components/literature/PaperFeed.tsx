import { useQuery } from '@tanstack/react-query';
import { useState, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, Select } from '../../components/ui';
import { getLiteraturePapers } from '../../api';
import { useT } from '../../i18n';
import type { LiteratureSubscription } from '../../types';
import PaperCard from './PaperCard';

interface Props {
  subscriptions: LiteratureSubscription[];
  onConvertToTask: (paperId: string, subscriptionId: string, title: string, abstract: string) => void;
}

export default function PaperFeed({ subscriptions, onConvertToTask }: Props) {
  const t = useT();
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<string | undefined>(undefined);
  const [unreadOnly, setUnreadOnly] = useState(false);

  const papersQuery = useQuery({
    queryKey: ['literature-papers', selectedSubscriptionId, unreadOnly],
    queryFn: () => getLiteraturePapers({
      subscription_id: selectedSubscriptionId,
      unread_only: unreadOnly || undefined,
      limit: 50,
    }),
  });

  const handleRefresh = useCallback(() => {
    papersQuery.refetch();
  }, [papersQuery]);

  const papers = papersQuery.data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Select
          value={selectedSubscriptionId ?? ''}
          onChange={(e) => setSelectedSubscriptionId(e.target.value || undefined)}
          className="w-auto min-w-[160px]"
        >
          <option value="">{t('literature.mySubscriptions')}</option>
          {subscriptions.map((sub) => (
            <option key={sub.subscription_id} value={sub.subscription_id}>
              {sub.label}
            </option>
          ))}
        </Select>

        <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
            className="rounded border-[var(--border)]"
          />
          {t('literature.unreadOnly')}
        </label>

        <Button variant="secondary" size="sm" onClick={handleRefresh} className="ml-auto">
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          {t('literature.refresh')}
        </Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto">
        {papersQuery.isLoading && papers.length === 0 && (
          <p className="py-8 text-center text-xs text-[var(--text-tertiary)]">{t('common.loading')}</p>
        )}

        {papers.length === 0 && !papersQuery.isLoading && (
          <p className="py-8 text-center text-xs text-[var(--text-tertiary)]">{t('literature.noPapers')}</p>
        )}

        {papers.map((paper) => (
          <PaperCard
            key={`${paper.paper_id}-${paper.subscription_id}`}
            paper={paper}
            onConvertToTask={onConvertToTask}
            onReadChange={() => papersQuery.refetch()}
          />
        ))}
      </div>
    </div>
  );
}
