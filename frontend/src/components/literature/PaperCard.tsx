import { Bookmark, ExternalLink, FileText, Eye, EyeOff, Sparkles } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getLiteratureSummary,
  requestLiteratureSummary,
  updateLiteraturePaperState,
} from '@/shared/api';
import { Badge, Button } from '@design-system/primitives';
import { queryKeys } from '@/shared/api/queryKeys';
import type { LiteraturePaperListItem, LiteratureSummaryStatus } from '@/shared/types';
import { useLocale, useT } from '@/shared/i18n';

interface Props {
  paper: LiteraturePaperListItem;
}

const activeSummaryStatuses = new Set<LiteratureSummaryStatus>(['queued', 'generating']);

function formatDate(value: string | null, locale: 'en' | 'zh'): string {
  if (!value) return '';
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(value));
}

export default function PaperCard({ paper }: Props) {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const summaryQuery = useQuery({
    queryKey: queryKeys.literature.summary(paper.paper_id),
    queryFn: () => getLiteratureSummary(paper.paper_id),
    refetchInterval: (query) =>
      activeSummaryStatuses.has(query.state.data?.status ?? 'not_requested') ? 5000 : false,
  });
  const summary = summaryQuery.data;

  const invalidatePaperData = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.literature.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.literature.overview });
    void queryClient.invalidateQueries({ queryKey: queryKeys.literature.paper(paper.paper_id) });
  };

  const stateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof updateLiteraturePaperState>[1]) =>
      updateLiteraturePaperState(paper.paper_id, payload),
    onSuccess: () => invalidatePaperData(),
  });
  const summaryMutation = useMutation({
    mutationFn: () => requestLiteratureSummary(paper.paper_id, locale === 'zh' ? 'zh' : 'en'),
    onSuccess: (nextSummary) => {
      queryClient.setQueryData(queryKeys.literature.summary(paper.paper_id), nextSummary);
    },
  });

  const isSummaryActive = activeSummaryStatuses.has(summary?.status ?? 'not_requested');
  const summaryLabel = summary?.status === 'completed'
    ? t('literature.summaryReady')
    : summary?.status === 'failed'
      ? t('literature.summaryFailed')
      : isSummaryActive
        ? t('literature.summaryInProgress')
        : t('literature.generateSummary');

  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <Badge>{paper.primary_category}</Badge>
            {!paper.user_state.is_read && <Badge variant="secondary">{t('literature.newPaper')}</Badge>}
            {paper.user_state.is_saved && <Badge variant="outline">{t('literature.saved')}</Badge>}
          </div>
          <h3 className="text-base font-semibold leading-snug text-[var(--text)]">{paper.title}</h3>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            {paper.authors.join(', ')}
            {paper.published_at && ` · ${t('literature.published')} ${formatDate(paper.published_at, locale)}`}
            {paper.updated_at && paper.updated_at !== paper.published_at && ` · ${t('literature.updated')} ${formatDate(paper.updated_at, locale)}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            aria-label={paper.user_state.is_read ? t('literature.markUnread') : t('literature.markRead')}
            title={paper.user_state.is_read ? t('literature.markUnread') : t('literature.markRead')}
            onClick={() => stateMutation.mutate({ is_read: !paper.user_state.is_read })}
            className="rounded-lg p-2 text-[var(--text-tertiary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
          >
            {paper.user_state.is_read ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
          <button
            type="button"
            aria-label={paper.user_state.is_saved ? t('literature.unsave') : t('literature.savePaper')}
            title={paper.user_state.is_saved ? t('literature.unsave') : t('literature.savePaper')}
            onClick={() => stateMutation.mutate({ is_saved: !paper.user_state.is_saved })}
            className={`rounded-lg p-2 transition hover:bg-[var(--bg-secondary)] ${paper.user_state.is_saved ? 'text-[var(--apple-blue)]' : 'text-[var(--text-tertiary)] hover:text-[var(--text)]'}`}
          >
            <Bookmark size={16} fill={paper.user_state.is_saved ? 'currentColor' : 'none'} />
          </button>
        </div>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)] line-clamp-3">{paper.abstract}</p>

      {paper.matched_topics.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {paper.matched_topics.map((topic) => (
            <span key={topic.topic_id} title={topic.reasons.join('，')}>
              <Badge variant="outline">{topic.label}</Badge>
            </span>
          ))}
        </div>
      )}

      {summary?.status === 'completed' && summary.text && (
        <div className="mt-3 rounded-lg bg-[var(--bg-secondary)] p-3">
          <p className="text-xs font-medium text-[var(--text)]">{t('literature.summary')}</p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)] line-clamp-4">{summary.text}</p>
        </div>
      )}
      {summary?.status === 'failed' && summary.error && (
        <p className="mt-3 text-xs text-[var(--danger)]">{summary.error}</p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
        <Button
          variant="secondary"
          size="sm"
          isLoading={summaryMutation.isPending || isSummaryActive}
          disabled={summary?.status === 'completed'}
          onClick={() => summaryMutation.mutate()}
        >
          <Sparkles className="mr-1 h-3.5 w-3.5" />
          {summaryLabel}
        </Button>
        <a
          href={paper.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
        >
          <ExternalLink size={14} /> {t('literature.viewSource')}
        </a>
        <a
          href={paper.pdf_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
        >
          <FileText size={14} /> PDF
        </a>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          onClick={() => stateMutation.mutate({ is_ignored: true })}
        >
          {t('literature.ignore')}
        </Button>
      </div>
    </article>
  );
}
