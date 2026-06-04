import { useQuery, useMutation } from '@tanstack/react-query';
import { useState, useCallback } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, Select } from '../../components/ui';
import { getLiteratureFetchStatus, getLiteraturePapers, triggerLiteratureFetch } from '../../api';
import { useT } from '../../i18n';
import type { LiteratureSubscription } from '../../types';
import PaperCard from './PaperCard';

interface Props {
  subscriptions: LiteratureSubscription[];
  selectedSubscriptionId?: string;
  onSubscriptionChange?: (id: string | undefined) => void;
  onConvertToTask: (paperId: string, subscriptionId: string, title: string, abstract: string) => void;
}

const FETCH_POLL_INTERVAL_MS = 1000;
const FETCH_POLL_ATTEMPTS = 60;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function PaperFeed({ subscriptions, selectedSubscriptionId, onSubscriptionChange, onConvertToTask }: Props) {
  const t = useT();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const papersQuery = useQuery({
    queryKey: ['literature-papers', selectedSubscriptionId, unreadOnly],
    queryFn: () => getLiteraturePapers({
      subscription_id: selectedSubscriptionId,
      unread_only: unreadOnly || undefined,
      limit: 50,
    }),
  });

  const fetchMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSubscriptionId) {
        return { status: 'skipped' };
      }
      await triggerLiteratureFetch(selectedSubscriptionId);
      for (let attempt = 0; attempt < FETCH_POLL_ATTEMPTS; attempt += 1) {
        const status = await getLiteratureFetchStatus(selectedSubscriptionId);
        if (status.status === 'completed') {
          return status;
        }
        if (status.status === 'failed') {
          throw new Error(status.error ?? 'Literature fetch failed');
        }
        await wait(FETCH_POLL_INTERVAL_MS);
      }
      return { status: 'timeout' };
    },
  });

  const handleRefresh = useCallback(() => {
    if (selectedSubscriptionId) {
      fetchMutation.mutate(undefined, {
        onSettled: () => papersQuery.refetch(),
      });
    } else {
      papersQuery.refetch();
    }
  }, [selectedSubscriptionId, fetchMutation, papersQuery]);

  const papers = papersQuery.data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Select
          value={selectedSubscriptionId ?? ''}
          onChange={(e) => onSubscriptionChange?.(e.target.value || undefined)}
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

        <Button variant="secondary" size="sm" onClick={handleRefresh} isLoading={fetchMutation.isPending} className="ml-auto">
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
