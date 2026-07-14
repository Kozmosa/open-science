import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, RefreshCw, Sparkles } from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardGrid,
  CardHeader,
  EmptyState,
  PageHeader,
  PageShell,
  Skeleton,
  StatusBadge,
  UpdateStrip,
} from '@design-system';
import { useAuth } from '@features/auth';
import {
  getOverviewRefreshJob,
  getTodayOverview,
  requestTodayOverviewRefresh,
  type OverviewDisplayCard,
  type OverviewDisplayCardId,
  type OverviewRefreshJob,
} from '@features/domain';
import { useDomainCapabilities } from '@features/domain';
import { createIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { useLocale, useT } from '@/shared/i18n';
import { useUserPreference } from '@/shared/hooks/useUserPreference';
import { extractErrorMessage } from '@/shared/utils/error';

const REORDERABLE_CARD_IDS: OverviewDisplayCardId[] = ['progress', 'literature', 'continue', 'resources'];
const REFRESH_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 10_000] as const;
const MAX_REFRESH_POLL_MS = 60_000;
const ACTIVE_JOB_STATUSES = new Set(['queued', 'retry_wait', 'running']);
const SUCCESS_JOB_STATUSES = new Set(['succeeded', 'partial', 'completed']);

type JsonRecord = Record<string, unknown>;

function isCardOrder(value: unknown): value is OverviewDisplayCardId[] {
  return Array.isArray(value)
    && value.length === REORDERABLE_CARD_IDS.length
    && new Set(value).size === REORDERABLE_CARD_IDS.length
    && value.every((item) => REORDERABLE_CARD_IDS.includes(item as OverviewDisplayCardId));
}

function asRecord(value: unknown): JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function asRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function stringValue(record: JsonRecord, key: string): string | null {
  return typeof record[key] === 'string' ? record[key] : null;
}

function numberValue(record: JsonRecord, key: string): number {
  return typeof record[key] === 'number' && Number.isFinite(record[key]) ? record[key] : 0;
}

function formatDate(value: string | null | undefined, locale: 'en' | 'zh'): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed);
}

function statusTone(status: string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'ok' || status === 'succeeded' || status === 'completed') return 'success';
  if (status === 'failed') return 'danger';
  if (status === 'stale' || status === 'partial' || status === 'unavailable') return 'warning';
  return 'neutral';
}

function itemLabel(item: JsonRecord): string {
  return stringValue(item, 'label')
    ?? stringValue(item, 'title')
    ?? stringValue(item, 'summary')
    ?? stringValue(item, 'kind')
    ?? 'OpenScience item';
}

function itemHref(item: JsonRecord): string | null {
  const kind = stringValue(item, 'kind');
  if (kind === 'task') {
    const taskId = stringValue(item, 'task_id');
    return taskId ? `/tasks?task=${encodeURIComponent(taskId)}` : '/tasks';
  }
  if (kind === 'project' || kind === 'project_without_workspace') {
    const projectId = stringValue(item, 'id') ?? stringValue(item, 'project_id');
    return projectId ? `/projects?project=${encodeURIComponent(projectId)}` : '/projects';
  }
  if (kind === 'workspace') {
    const workspaceId = stringValue(item, 'id') ?? stringValue(item, 'workspace_id');
    return workspaceId ? `/workspaces?workspace=${encodeURIComponent(workspaceId)}` : '/workspaces';
  }
  if (kind === 'missing_resource_snapshot' || stringValue(item, 'environment_id')) return '/resources';
  return null;
}

function hasDisplayData(cards: OverviewDisplayCard[]): boolean {
  return cards.some((card) => {
    const data = asRecord(card.data);
    if (card.id === 'attention') return asRecords(data.items).length > 0;
    if (card.id === 'progress') return asRecords(data.tasks).length > 0;
    if (card.id === 'literature') {
      return numberValue(data, 'unread_count') > 0
        || numberValue(data, 'updated_count') > 0
        || asRecords(data.papers).length > 0;
    }
    if (card.id === 'continue') return asRecords(data.items).length > 0;
    return numberValue(data, 'environment_count') > 0 || asRecords(data.environments).length > 0;
  });
}

function OverviewItems({ items, emptyMessage }: { items: JsonRecord[]; emptyMessage: string }) {
  if (items.length === 0) return <p className="text-sm text-[var(--osci-color-text-muted)]">{emptyMessage}</p>;
  return (
    <div className="divide-y divide-[var(--osci-color-border-subtle)]">
      {items.map((item, index) => {
        const href = itemHref(item);
        const label = itemLabel(item);
        const content = (
          <>
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {stringValue(item, 'status') ? <Badge variant="secondary">{stringValue(item, 'status')}</Badge> : null}
            {href ? <ArrowRight aria-hidden="true" size={14} /> : null}
          </>
        );
        return href ? (
          <a key={`${label}:${index}`} href={href} className="flex items-center gap-2 py-3 text-sm text-[var(--osci-color-text)] hover:text-[var(--osci-color-primary)]">
            {content}
          </a>
        ) : (
          <div key={`${label}:${index}`} className="flex items-center gap-2 py-3 text-sm text-[var(--osci-color-text)]">
            {content}
          </div>
        );
      })}
    </div>
  );
}

function TodayCard({ card }: { card: OverviewDisplayCard }) {
  const t = useT();
  const locale = useLocale();
  const data = asRecord(card.data);
  let body;
  if (card.id === 'attention') {
    body = <OverviewItems items={asRecords(data.items)} emptyMessage={t('pages.today.noAttention')} />;
  } else if (card.id === 'progress') {
    body = <OverviewItems items={asRecords(data.tasks).map((item) => ({ kind: 'task', ...item }))} emptyMessage={t('pages.today.noTasks')} />;
  } else if (card.id === 'literature') {
    const papers = asRecords(data.papers);
    body = (
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Badge>{t('pages.today.unread', { count: numberValue(data, 'unread_count') })}</Badge>
          <Badge variant="secondary">{t('pages.today.updated', { count: numberValue(data, 'updated_count') })}</Badge>
        </div>
        {papers.length > 0 ? (
          <div className="divide-y divide-[var(--osci-color-border-subtle)]">
            {papers.map((paper, index) => {
              const paperId = stringValue(paper, 'paper_id');
              return (
                <a key={paperId ?? index} href={paperId ? `/literature?paper=${encodeURIComponent(paperId)}` : '/literature'} className="flex items-center gap-2 py-3 text-sm text-[var(--osci-color-text)] hover:text-[var(--osci-color-primary)]">
                  <span className="min-w-0 flex-1 truncate">{itemLabel(paper)}</span>
                  {stringValue(paper, 'primary_category') ? <Badge variant="outline">{stringValue(paper, 'primary_category')}</Badge> : null}
                  <ArrowRight aria-hidden="true" size={14} />
                </a>
              );
            })}
          </div>
        ) : <p className="text-sm text-[var(--osci-color-text-muted)]">{t('pages.today.noLiterature')}</p>}
      </div>
    );
  } else if (card.id === 'continue') {
    body = <OverviewItems items={asRecords(data.items)} emptyMessage={t('pages.today.noRecentWork')} />;
  } else {
    body = (
      <div className="space-y-3">
        <Badge variant="secondary">{t('pages.today.environments', { count: numberValue(data, 'environment_count') })}</Badge>
        <OverviewItems items={asRecords(data.environments)} emptyMessage={t('pages.today.noResources')} />
      </div>
    );
  }

  return (
    <Card data-testid={`today-card-${card.id}`} className={card.id === 'attention' ? 'border-[var(--osci-color-warning-border)]' : undefined}>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 pr-12">
        <h2 className="text-base font-semibold text-[var(--osci-color-text)]">{t(`pages.today.cards.${card.id}`)}</h2>
        <StatusBadge tone={statusTone(card.source_status)}>{card.source_status}</StatusBadge>
      </CardHeader>
      <CardBody className="space-y-4 pt-4">
        {body}
        <div className="space-y-1 border-t border-[var(--osci-color-border-subtle)] pt-3 text-xs text-[var(--osci-color-text-muted)]">
          <p>{t('pages.today.cutoff', { time: formatDate(card.data_cutoff_at, locale) })}</p>
          {card.error_summary ? <p className="text-[var(--osci-color-danger-foreground)]">{t('pages.today.errorSummary', { error: card.error_summary })}</p> : null}
        </div>
      </CardBody>
    </Card>
  );
}

export default function TodayPage() {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { isLoading: capabilityLoading, availability } = useDomainCapabilities();
  const overviewAvailability = availability('overview_snapshot');
  const overviewQuery = useQuery({
    queryKey: queryKeys.domain.overview,
    queryFn: getTodayOverview,
    enabled: overviewAvailability.available,
  });
  const [cardOrder, setCardOrder] = useUserPreference<OverviewDisplayCardId[]>(
    user?.id ?? 'anonymous',
    'today-card-order',
    REORDERABLE_CARD_IDS,
    isCardOrder,
  );
  const refreshKeyRef = useRef(createIdempotencyKey('overview.today.refresh'));
  const refreshStartedAtRef = useRef<number | null>(null);
  const [refreshJob, setRefreshJob] = useState<OverviewRefreshJob | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);

  const completeRefresh = useCallback((job: OverviewRefreshJob) => {
    setRefreshJob(job);
    if (SUCCESS_JOB_STATUSES.has(job.status)) {
      refreshKeyRef.current = createIdempotencyKey('overview.today.refresh');
      void queryClient.invalidateQueries({ queryKey: queryKeys.domain.overview });
    }
  }, [queryClient]);

  const refreshMutation = useMutation({
    mutationFn: () => requestTodayOverviewRefresh(refreshKeyRef.current),
    onSuccess: (job) => {
      setPollError(null);
      setPollTimedOut(false);
      setPollAttempt(0);
      refreshStartedAtRef.current = Date.now();
      completeRefresh(job);
    },
    onError: (error) => setPollError(extractErrorMessage(error)),
  });

  useEffect(() => {
    if (!refreshJob || !ACTIVE_JOB_STATUSES.has(refreshJob.status) || pollTimedOut) return;
    const startedAt = refreshStartedAtRef.current ?? Date.now();
    refreshStartedAtRef.current = startedAt;
    const timer = window.setTimeout(
      () => setPollTimedOut(true),
      Math.max(0, MAX_REFRESH_POLL_MS - (Date.now() - startedAt)),
    );
    return () => window.clearTimeout(timer);
  }, [pollTimedOut, refreshJob]);

  useEffect(() => {
    if (!refreshJob || !ACTIVE_JOB_STATUSES.has(refreshJob.status) || pollTimedOut) return;
    const startedAt = refreshStartedAtRef.current ?? Date.now();
    refreshStartedAtRef.current = startedAt;
    const elapsed = Date.now() - startedAt;
    const remaining = MAX_REFRESH_POLL_MS - elapsed;
    if (remaining <= 0) return;
    const delay = Math.min(REFRESH_DELAYS_MS[Math.min(pollAttempt, REFRESH_DELAYS_MS.length - 1)], remaining);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (Date.now() - startedAt >= MAX_REFRESH_POLL_MS) {
        if (!cancelled) setPollTimedOut(true);
        return;
      }
      void getOverviewRefreshJob(refreshJob.job_id)
        .then((job) => {
          if (cancelled) return;
          setPollError(null);
          completeRefresh(job);
          if (ACTIVE_JOB_STATUSES.has(job.status)) setPollAttempt((attempt) => attempt + 1);
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          setPollError(extractErrorMessage(error));
          setPollAttempt((attempt) => attempt + 1);
        });
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [completeRefresh, pollAttempt, pollTimedOut, refreshJob]);

  const displayCards = useMemo(() => overviewQuery.data?.display_cards ?? [], [overviewQuery.data]);
  const groups = useMemo(() => [{
    id: 'today',
    cards: displayCards.map((card) => ({ id: card.id, kind: card.id })),
  }], [displayCards]);
  const cardsById = useMemo(() => new Map(displayCards.map((card) => [card.id, card])), [displayCards]);
  const isRefreshing = Boolean(refreshJob && ACTIVE_JOB_STATUSES.has(refreshJob.status) && !pollTimedOut);
  const stripTone = refreshJob?.status === 'failed' || pollError
    ? 'danger'
    : pollTimedOut || overviewQuery.data?.source_status === 'partial'
      ? 'warning'
      : isRefreshing
        ? 'info'
        : overviewQuery.data
          ? 'success'
          : 'neutral';

  if (capabilityLoading) {
    return <PageShell variant="canvas"><div className="p-6"><Skeleton className="h-48" /></div></PageShell>;
  }
  if (!overviewAvailability.available) {
    return (
      <PageShell variant="canvas">
        <div className="p-4 md:p-6">
          <EmptyState title={t('pages.today.unavailableTitle')} message={overviewAvailability.reason ?? t('pages.today.unavailableDescription')} />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell variant="canvas">
      <div className="mx-auto flex w-full max-w-[1450px] flex-col gap-5 p-4 md:p-6">
        <PageHeader
          eyebrow={t('pages.today.eyebrow')}
          title={t('pages.today.title')}
          description={t('pages.today.description')}
          actions={(
            <Button
              size="sm"
              className="gap-2"
              onClick={() => refreshMutation.mutate()}
              isLoading={refreshMutation.isPending || isRefreshing}
              disabled={isRefreshing}
            >
              <RefreshCw aria-hidden="true" size={14} />
              {t('pages.today.refresh')}
            </Button>
          )}
        />

        <UpdateStrip tone={stripTone} data-testid="today-update-strip">
          {pollError ? t('pages.today.refreshFailed', { error: pollError })
            : pollTimedOut ? t('pages.today.refreshTimedOut')
              : refreshJob ? t('pages.today.refreshStatus', { status: refreshJob.status })
                : overviewQuery.data ? t('pages.today.refreshed', { time: formatDate(overviewQuery.data.data_cutoff_at, locale) })
                  : t('pages.today.loading')}
          {overviewQuery.data?.next_scheduled_at ? <span className="ml-2">{t('pages.today.nextRefresh', { time: formatDate(overviewQuery.data.next_scheduled_at, locale) })}</span> : null}
        </UpdateStrip>

        {overviewQuery.isLoading ? <div className="grid gap-5 md:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div> : null}

        {!overviewQuery.isLoading && !hasDisplayData(displayCards) ? (
          <EmptyState
            icon={<Sparkles aria-hidden="true" size={28} />}
            title={t('pages.today.emptyTitle')}
            message={t('pages.today.emptyDescription')}
            actions={<div className="flex flex-wrap justify-center gap-2"><a className="text-sm font-medium text-[var(--osci-color-primary)]" href="/projects">Projects</a><a className="text-sm font-medium text-[var(--osci-color-primary)]" href="/literature">Literature</a></div>}
          />
        ) : null}

        {hasDisplayData(displayCards) ? (
          <CardGrid
            groups={groups}
            renderCard={(cardId) => {
              const card = cardsById.get(cardId as OverviewDisplayCardId);
              return card ? <TodayCard card={card} /> : null;
            }}
            cardOrder={cardOrder}
            onCardOrderChange={(order) => setCardOrder(order.filter((id): id is OverviewDisplayCardId => id !== 'attention' && REORDERABLE_CARD_IDS.includes(id as OverviewDisplayCardId)))}
            columns={2}
            className="items-stretch [&>div]:min-h-72"
          />
        ) : null}
      </div>
    </PageShell>
  );
}
