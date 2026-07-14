import { useMemo, useState } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardBody,
  DetailDrawer,
  EmptyState,
  NativeSelect,
  PageHeader,
  PageShell,
  StatusBadge,
  UpdateStrip,
  ViewToolbar,
} from '@design-system';
import {
  createLiteratureCheck,
  createLiteratureResearchTask,
  getLiteratureOverview,
  getLiteraturePaper,
  getLiteraturePapers,
  getLiteratureResearchTask,
  getLiteratureResearchTasks,
  getLiteratureSummary,
  getLiteratureTopics,
  requestLiteratureSummary,
  updateLiteraturePaperState,
} from '@/shared/api';
import { createIdempotencyKey, semanticMutationValue } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import type { LiteratureCheckStatus, LiteratureInboxView, LiteratureTaskIntent } from '@/shared/types';
import { useLocale, useT } from '@/shared/i18n';
import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';

const VIEWS: LiteratureInboxView[] = ['today', 'unread', 'saved', 'updated', 'all'];
const ACTIVE_CHECK_STATUSES = new Set<LiteratureCheckStatus>(['planned', 'checking', 'partial', 'retrying']);
const ACTIVE_INTENT_STATUSES = new Set(['planned', 'creating_task', 'task_created', 'retry_wait']);
const POLL_INTERVALS = [5_000, 10_000, 20_000, 30_000];

function progressiveInterval(dataUpdateCount: number): number {
  return POLL_INTERVALS[Math.min(dataUpdateCount, POLL_INTERVALS.length - 1)];
}

function formatDate(value: string | null, locale: 'en' | 'zh'): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function intentStorageKey(paperId: string): string {
  return `openscience:literature-intent:${paperId}`;
}

function readPendingIntent(paperId: string | null): { key: string; semantic: string } | null {
  if (!paperId) return null;
  try {
    const parsed = JSON.parse(localStorage.getItem(intentStorageKey(paperId)) ?? 'null') as { key?: unknown; semantic?: unknown } | null;
    return parsed && typeof parsed.key === 'string' && typeof parsed.semantic === 'string' ? { key: parsed.key, semantic: parsed.semantic } : null;
  } catch {
    return null;
  }
}

export default function LiteraturePage() {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [taskFlowOpen, setTaskFlowOpen] = useState(false);
  const [pendingIntentOverride, setPendingIntentOverride] = useState<{ paperId: string; key: string; semantic: string } | null>(null);
  const section = searchParams.get('section') === 'topics' ? 'topics' : 'inbox';
  const requestedView = searchParams.get('view');
  const view = VIEWS.includes(requestedView as LiteratureInboxView) ? requestedView as LiteratureInboxView : 'today';
  const topicId = searchParams.get('topic') ?? undefined;
  const category = searchParams.get('category') ?? undefined;
  const selectedPaperId = searchParams.get('paper');
  const pendingIntent = pendingIntentOverride?.paperId === selectedPaperId ? pendingIntentOverride : readPendingIntent(selectedPaperId);

  const updateSearch = (changes: Record<string, string | null>) => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    return next;
  });

  const overviewQuery = useQuery({
    queryKey: queryKeys.literature.overview,
    queryFn: getLiteratureOverview,
    refetchInterval: (query) => ACTIVE_CHECK_STATUSES.has(query.state.data?.active_check?.status ?? 'completed') ? progressiveInterval(query.state.dataUpdateCount) : false,
  });
  const topicsQuery = useQuery({ queryKey: queryKeys.literature.topics, queryFn: getLiteratureTopics });
  const paperFilters = useMemo(() => ({ view, topic_id: topicId, category, limit: 30 }), [category, topicId, view]);
  const papersQuery = useInfiniteQuery({
    queryKey: queryKeys.literature.papers(paperFilters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => getLiteraturePapers({ ...paperFilters, cursor: pageParam }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const paperQuery = useQuery({ queryKey: queryKeys.literature.paper(selectedPaperId), queryFn: () => getLiteraturePaper(selectedPaperId!), enabled: Boolean(selectedPaperId) });
  const summaryQuery = useQuery({
    queryKey: queryKeys.literature.summary(selectedPaperId),
    queryFn: () => getLiteratureSummary(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: (query) => ['queued', 'generating'].includes(query.state.data?.status ?? '') ? progressiveInterval(query.state.dataUpdateCount) : false,
  });
  const researchTasksQuery = useQuery({
    queryKey: queryKeys.literature.researchTasks(selectedPaperId),
    queryFn: () => getLiteratureResearchTasks(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: (query) => query.state.data?.items.some((item) => ACTIVE_INTENT_STATUSES.has(item.status)) ? progressiveInterval(query.state.dataUpdateCount) : false,
  });
  const recoveredIntentQuery = useQuery({
    queryKey: ['literature', 'research-task', selectedPaperId, pendingIntent?.key],
    queryFn: () => getLiteratureResearchTask(selectedPaperId!, pendingIntent!.key),
    enabled: Boolean(selectedPaperId && pendingIntent?.key),
    refetchInterval: (query) => ACTIVE_INTENT_STATUSES.has(query.state.data?.status ?? '') ? progressiveInterval(query.state.dataUpdateCount) : false,
  });

  const checkMutation = useMutation({
    mutationFn: () => createLiteratureCheck(),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: queryKeys.literature.overview }); void queryClient.invalidateQueries({ queryKey: queryKeys.literature.checks }); },
  });
  const stateMutation = useMutation({
    mutationFn: ({ paperId, payload }: { paperId: string; payload: { is_read?: boolean; is_saved?: boolean; is_ignored?: boolean } }) => updateLiteraturePaperState(paperId, payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.literature.all }),
  });
  const summaryMutation = useMutation({
    mutationFn: () => requestLiteratureSummary(selectedPaperId!, locale === 'zh' ? 'zh' : 'en'),
    onSuccess: (summary) => queryClient.setQueryData(queryKeys.literature.summary(selectedPaperId), summary),
  });
  const papers = papersQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const overview = overviewQuery.data;
  const activeCheck = overview?.active_check;
  const stripTone = activeCheck?.status === 'failed' ? 'danger' : activeCheck?.status === 'partial' || activeCheck?.status === 'retrying' ? 'warning' : ACTIVE_CHECK_STATUSES.has(activeCheck?.status ?? 'completed') ? 'info' : 'neutral';

  const submitResearchTask = async (selection: { project_id: string; workspace_id: string; task_preset: string; title?: string }) => {
    if (!selectedPaperId) return;
    const semantic = semanticMutationValue(selection);
    const previous = readPendingIntent(selectedPaperId);
    const key = previous?.semantic === semantic ? previous.key : createIdempotencyKey(`literature.research-task.${selectedPaperId}`);
    localStorage.setItem(intentStorageKey(selectedPaperId), JSON.stringify({ key, semantic }));
    setPendingIntentOverride({ paperId: selectedPaperId, key, semantic });
    const intent = await createLiteratureResearchTask(selectedPaperId, selection, key);
    queryClient.setQueryData(['literature', 'research-task', selectedPaperId, key], intent);
    void queryClient.invalidateQueries({ queryKey: queryKeys.literature.researchTasks(selectedPaperId) });
  };

  return <PageShell variant="canvas">
    <div className="mx-auto flex w-full max-w-[1450px] flex-col gap-4 p-4 md:p-6">
      <PageHeader eyebrow={t('literature.eyebrow')} title={t('literature.inbox')} description={t('literature.inboxDescription')} actions={<Button onClick={() => checkMutation.mutate()} isLoading={checkMutation.isPending || Boolean(activeCheck && ACTIVE_CHECK_STATUSES.has(activeCheck.status))}>{t('literature.checkLatest')}</Button>} />
      <UpdateStrip tone={stripTone}>Last check: {formatDate(overview?.last_successful_check_at ?? null, locale)} · Next check: {formatDate(overview?.next_scheduled_check_at ?? null, locale)}{activeCheck ? ` · ${activeCheck.status}${activeCheck.error ? ` · ${activeCheck.error}` : ''}` : ''}</UpdateStrip>
      <ViewToolbar>
        <Button size="sm" variant={section === 'inbox' ? 'primary' : 'secondary'} onClick={() => updateSearch({ section: null })}>Inbox</Button>
        <Button size="sm" variant={section === 'topics' ? 'primary' : 'secondary'} onClick={() => updateSearch({ section: 'topics' })}>{t('literature.manageTopics')}</Button>
        {section === 'inbox' ? <><div className="h-6 w-px bg-[var(--osci-color-border)]" />{VIEWS.map((item) => <Button key={item} size="sm" variant={view === item ? 'primary' : 'ghost'} onClick={() => updateSearch({ view: item === 'today' ? null : item })}>{t(`literature.views.${item}`)}</Button>)}<div className="ml-auto flex gap-2"><NativeSelect aria-label={t('literature.filterTopic')} value={topicId ?? ''} onChange={(event) => updateSearch({ topic: event.target.value || null })}><option value="">{t('literature.allTopics')}</option>{(topicsQuery.data?.items ?? []).map((topic) => <option key={topic.topic_id} value={topic.topic_id}>{topic.label}</option>)}</NativeSelect><NativeSelect aria-label={t('literature.filterCategory')} value={category ?? ''} onChange={(event) => updateSearch({ category: event.target.value || null })}><option value="">{t('literature.allCategories')}</option>{['cs.AI', 'cs.CL', 'cs.CV', 'cs.LG', 'cs.RO', 'stat.ML'].map((item) => <option key={item}>{item}</option>)}</NativeSelect></div></> : null}
      </ViewToolbar>

      {section === 'topics' ? <Card><CardBody className="space-y-3 p-5">{(topicsQuery.data?.items ?? []).map((topic) => <div key={topic.topic_id} className="rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3"><div className="flex items-center gap-2"><h2 className="font-semibold text-[var(--osci-color-text)]">{topic.label}</h2><StatusBadge tone={topic.is_active ? 'success' : 'neutral'}>{topic.is_active ? 'active' : 'paused'}</StatusBadge></div><p className="mt-1 text-sm text-[var(--osci-color-text-secondary)]">{topic.categories.join(' · ')} · {topic.include_terms.join(', ')}</p></div>)}{!topicsQuery.isLoading && (topicsQuery.data?.items.length ?? 0) === 0 ? <EmptyState message={t('literature.noTopics')} /> : null}</CardBody></Card> : <Card><CardBody className="divide-y divide-[var(--osci-color-border-subtle)] p-0">{papers.map((paper) => <article key={paper.paper_id} className="flex flex-col gap-3 p-4 md:flex-row md:items-start md:justify-between"><button type="button" className="min-w-0 flex-1 text-left" onClick={() => updateSearch({ paper: paper.paper_id })}><div className="flex flex-wrap items-center gap-2"><Badge>{paper.primary_category}</Badge>{!paper.user_state.is_read ? <Badge variant="secondary">{t('literature.newPaper')}</Badge> : null}{paper.user_state.is_saved ? <Badge variant="outline">{t('literature.saved')}</Badge> : null}{paper.matched_topics.map((topic) => <Badge key={topic.topic_id} variant="outline">{topic.label}</Badge>)}</div><h2 className="mt-2 font-semibold text-[var(--osci-color-text)]">{paper.title}</h2><p className="mt-1 text-xs text-[var(--osci-color-text-muted)]">{paper.authors.join(', ')} · {formatDate(paper.updated_at ?? paper.published_at, locale)}</p><p className="mt-2 line-clamp-2 text-sm text-[var(--osci-color-text-secondary)]">{paper.abstract}</p></button><div className="flex shrink-0 gap-2"><Button size="sm" variant="secondary" onClick={() => stateMutation.mutate({ paperId: paper.paper_id, payload: { is_read: !paper.user_state.is_read } })}>{paper.user_state.is_read ? t('literature.markUnread') : t('literature.markRead')}</Button><Button size="sm" variant="secondary" onClick={() => stateMutation.mutate({ paperId: paper.paper_id, payload: { is_saved: !paper.user_state.is_saved } })}>{paper.user_state.is_saved ? t('literature.unsave') : t('literature.savePaper')}</Button><Button size="sm" onClick={() => updateSearch({ paper: paper.paper_id })}>Details</Button></div></article>)}{!papersQuery.isLoading && papers.length === 0 ? <EmptyState message={t('literature.noPapers')} /> : null}{papersQuery.hasNextPage ? <div className="flex justify-center p-4"><Button variant="secondary" onClick={() => papersQuery.fetchNextPage()} isLoading={papersQuery.isFetchingNextPage}>{t('literature.loadMore')}</Button></div> : null}</CardBody></Card>}
    </div>

    <DetailDrawer open={Boolean(selectedPaperId)} onOpenChange={(open) => { if (!open) updateSearch({ paper: null }); }} title={paperQuery.data?.title ?? 'Paper details'}>
      {paperQuery.data ? <div className="space-y-5"><div className="flex flex-wrap gap-2"><Badge>{paperQuery.data.primary_category}</Badge>{paperQuery.data.matched_topics.map((topic) => <Badge key={topic.topic_id} variant="outline">{topic.label}</Badge>)}</div><p className="text-sm leading-relaxed text-[var(--osci-color-text-secondary)]">{paperQuery.data.abstract}</p><div><h3 className="font-semibold text-[var(--osci-color-text)]">Versions</h3><div className="mt-2 space-y-2">{paperQuery.data.versions.map((version) => <div key={version.version_id} className="flex justify-between text-sm"><span className="font-mono text-[var(--osci-color-text)]">{version.provider_version}</span><span className="text-[var(--osci-color-text-muted)]">{formatDate(version.updated_at ?? version.published_at, locale)}</span></div>)}</div></div><div><h3 className="font-semibold text-[var(--osci-color-text)]">Summary</h3>{summaryQuery.data?.status === 'completed' ? <p className="mt-2 whitespace-pre-wrap text-sm text-[var(--osci-color-text-secondary)]">{summaryQuery.data.text}</p> : <Button className="mt-2" variant="secondary" onClick={() => summaryMutation.mutate()} isLoading={summaryMutation.isPending || ['queued', 'generating'].includes(summaryQuery.data?.status ?? '')}>Generate summary</Button>}</div><div><div className="flex items-center justify-between"><h3 className="font-semibold text-[var(--osci-color-text)]">Research Tasks</h3><Button onClick={() => setTaskFlowOpen(true)}>Convert to research Task</Button></div><div className="mt-2 space-y-2">{researchTasksQuery.data?.items.map((intent: LiteratureTaskIntent) => <div key={intent.intent_id} className="rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-3 text-sm"><div className="flex items-center justify-between"><StatusBadge tone={intent.status === 'completed' ? 'success' : intent.status === 'failed' ? 'danger' : 'warning'}>{intent.status}</StatusBadge>{intent.task_id ? <a className="text-[var(--osci-color-primary)]" href={`/tasks?task=${encodeURIComponent(intent.task_id)}`}>{intent.task_id}</a> : null}</div>{intent.last_error ? <p className="mt-2 text-[var(--osci-color-danger-foreground)]">{intent.last_error}</p> : null}</div>)}{recoveredIntentQuery.data && !(researchTasksQuery.data?.items.some((item) => item.intent_id === recoveredIntentQuery.data.intent_id)) ? <StatusBadge tone="warning">Recovered {recoveredIntentQuery.data.status}</StatusBadge> : null}</div></div></div> : null}
    </DetailDrawer>
    <TaskCreateFlow isOpen={taskFlowOpen} source="literature" initialTitle={paperQuery.data?.title ? `Research: ${paperQuery.data.title}` : ''} onLiteratureSubmit={submitResearchTask} onClose={() => setTaskFlowOpen(false)} />
  </PageShell>;
}
