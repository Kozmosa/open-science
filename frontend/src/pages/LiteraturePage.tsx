import { BookOpen, Plus, RefreshCw, Settings2 } from 'lucide-react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  createLiteratureCheck,
  createLiteratureTopic,
  deleteLiteratureTopic,
  getLiteratureOverview,
  getLiteraturePapers,
  getLiteratureTopics,
  previewLiteratureTopic,
  updateLiteratureTopic,
} from '@/shared/api';
import { Alert, Badge, Button, Dialog, EmptyState, FormField, Input, PageShell, SectionCard, SectionHeader, SectionStack, StatusDot } from '@design-system';
import { queryKeys } from '@/shared/api/queryKeys';
import type { LiteratureCheckStatus, LiteratureInboxView, LiteratureTopic, LiteratureTopicInput } from '@/shared/types';
import { useLocale, useT } from '@/shared/i18n';
import PaperCard from '../components/literature/PaperCard';

const ARXIV_CATEGORIES = ['cs.AI', 'cs.CL', 'cs.CV', 'cs.LG', 'cs.RO', 'stat.ML'];
const VIEWS: LiteratureInboxView[] = ['today', 'unread', 'saved', 'updated', 'all'];
const ACTIVE_CHECK_STATUSES = new Set<LiteratureCheckStatus>(['planned', 'checking', 'partial', 'retrying']);

function initialTopicForm(topic?: LiteratureTopic): LiteratureTopicInput {
  return {
    label: topic?.label ?? '',
    include_terms: topic?.include_terms ?? [],
    exclude_terms: topic?.exclude_terms ?? [],
    categories: topic?.categories ?? [],
  };
}

function formatDate(value: string | null, locale: 'en' | 'zh'): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function checkDot(status: LiteratureCheckStatus | undefined): 'success' | 'warning' | 'error' | 'idle' {
  if (status === 'completed') return 'success';
  if (status === 'partial' || status === 'retrying') return 'warning';
  if (status === 'failed') return 'error';
  return 'idle';
}

interface TopicFormModalProps {
  topic: LiteratureTopic | null;
  isOpen: boolean;
  onClose: () => void;
}

function TopicFormModal({ topic, isOpen, onClose }: TopicFormModalProps) {
  const t = useT();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<LiteratureTopicInput>(() => initialTopicForm(topic ?? undefined));
  const [categoryError, setCategoryError] = useState(false);
  const previewMutation = useMutation({ mutationFn: (payload: LiteratureTopicInput) => previewLiteratureTopic(payload) });
  const saveMutation = useMutation({
    mutationFn: (payload: LiteratureTopicInput) =>
      topic ? updateLiteratureTopic(topic.topic_id, payload) : createLiteratureTopic(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.topics });
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.overview });
      onClose();
    },
  });

  const setTerms = (field: 'include_terms' | 'exclude_terms', value: string) => {
    setForm((current) => ({
      ...current,
      [field]: value.split(',').map((term) => term.trim()).filter(Boolean),
    }));
  };
  const toggleCategory = (category: string) => {
    setCategoryError(false);
    setForm((current) => ({
      ...current,
      categories: current.categories.includes(category)
        ? current.categories.filter((value) => value !== category)
        : [...current.categories, category],
    }));
  };
  const submit = () => {
    if (!form.categories.length) {
      setCategoryError(true);
      return;
    }
    saveMutation.mutate(form);
  };

  return (
    <Dialog isOpen={isOpen} onClose={onClose} title={topic ? t('literature.editTopic') : t('literature.newTopic')} size="lg">
      <div className="space-y-4">
        <FormField label={t('literature.topicName')}>
          <Input
            autoFocus
            value={form.label}
            onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
            placeholder={t('literature.topicNamePlaceholder')}
          />
        </FormField>
        <FormField label={t('literature.includeTerms')}>
          <Input
            value={form.include_terms.join(', ')}
            onChange={(event) => setTerms('include_terms', event.target.value)}
            placeholder={t('literature.termsPlaceholder')}
          />
        </FormField>
        <FormField label={t('literature.excludeTerms')}>
          <Input
            value={form.exclude_terms.join(', ')}
            onChange={(event) => setTerms('exclude_terms', event.target.value)}
            placeholder={t('literature.termsPlaceholder')}
          />
        </FormField>
        <div>
          <p className="text-sm font-medium text-[var(--text)]">{t('literature.categories')}</p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">{t('literature.categoryRequired')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {ARXIV_CATEGORIES.map((category) => {
              const selected = form.categories.includes(category);
              return (
                <button
                  key={category}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggleCategory(category)}
                  className={selected
                    ? 'rounded-full bg-[var(--apple-blue)] px-3 py-1 text-xs font-medium text-white'
                    : 'rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 py-1 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)]'}
                >
                  {category}
                </button>
              );
            })}
          </div>
          {categoryError && <p className="mt-2 text-xs text-[var(--danger)]">{t('literature.categoryRequired')}</p>}
        </div>

        {previewMutation.data && (
          <Alert variant={previewMutation.data.needs_check ? 'warning' : 'success'}>
            {t('literature.previewResult', {
              count: previewMutation.data.matched_count,
              coverage: previewMutation.data.local_coverage.paper_count,
            })}
          </Alert>
        )}
        {saveMutation.isError && <Alert>{t('literature.topicSaveFailed')}</Alert>}
        <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border)] pt-4">
          <Button variant="secondary" size="sm" onClick={() => previewMutation.mutate(form)} disabled={!form.categories.length}>
            {t('literature.previewMatches')}
          </Button>
          <Button size="sm" onClick={submit} isLoading={saveMutation.isPending} disabled={!form.label.trim()}>
            {topic ? t('common.save') : t('literature.createTopic')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function TopicsPanel({ onCreate, onEdit }: { onCreate: () => void; onEdit: (topic: LiteratureTopic) => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const topicsQuery = useQuery({ queryKey: queryKeys.literature.topics, queryFn: getLiteratureTopics });
  const updateMutation = useMutation({
    mutationFn: ({ topicId, isActive }: { topicId: string; isActive: boolean }) =>
      updateLiteratureTopic(topicId, { is_active: isActive }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.literature.topics }),
  });
  const deleteMutation = useMutation({
    mutationFn: deleteLiteratureTopic,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.topics });
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.all });
    },
  });
  const topics = topicsQuery.data?.items ?? [];

  return (
    <SectionStack gap={4}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeader title={t('literature.topics')} description={t('literature.topicsDescription')} size="md" />
        <Button size="sm" onClick={onCreate}><Plus className="mr-1 h-4 w-4" />{t('literature.newTopic')}</Button>
      </div>
      {topicsQuery.isLoading && <p className="text-sm text-[var(--text-secondary)]">{t('common.loading')}</p>}
      {!topicsQuery.isLoading && topics.length === 0 && (
        <EmptyState message={t('literature.noTopics')} icon={<BookOpen size={24} />} />
      )}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {topics.map((topic) => (
          <SectionCard key={topic.topic_id} className="p-4" header={
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-[var(--text)]">{topic.label}</h3>
                <Badge variant={topic.is_active ? 'default' : 'secondary'}>{topic.is_active ? t('literature.active') : t('literature.paused')}</Badge>
              </div>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">{topic.categories.join(' · ')}</p>
            </div>
          }>
            <div className="flex flex-wrap gap-1.5">
              {topic.include_terms.map((term) => <Badge key={term} variant="outline">{term}</Badge>)}
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="secondary" size="sm" onClick={() => onEdit(topic)}>{t('common.edit')}</Button>
              <Button variant="ghost" size="sm" onClick={() => updateMutation.mutate({ topicId: topic.topic_id, isActive: !topic.is_active })}>
                {topic.is_active ? t('literature.pause') : t('literature.resume')}
              </Button>
              <Button variant="ghost" size="sm" className="text-[var(--danger)]" onClick={() => deleteMutation.mutate(topic.topic_id)}>
                {t('common.delete')}
              </Button>
            </div>
          </SectionCard>
        ))}
      </div>
    </SectionStack>
  );
}

export default function LiteraturePage() {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [topicForForm, setTopicForForm] = useState<LiteratureTopic | null | undefined>(undefined);
  const section = searchParams.get('section') === 'topics' ? 'topics' : 'inbox';
  const requestedView = searchParams.get('view');
  const view = VIEWS.includes(requestedView as LiteratureInboxView) ? requestedView as LiteratureInboxView : 'today';
  const topicId = searchParams.get('topic') ?? undefined;
  const category = searchParams.get('category') ?? undefined;
  const overviewQuery = useQuery({
    queryKey: queryKeys.literature.overview,
    queryFn: getLiteratureOverview,
    refetchInterval: (query) => ACTIVE_CHECK_STATUSES.has(query.state.data?.active_check?.status ?? 'completed') ? 5000 : false,
  });
  const topicsQuery = useQuery({ queryKey: queryKeys.literature.topics, queryFn: getLiteratureTopics });
  const paperFilters = useMemo(() => ({ view, topic_id: topicId, category, limit: 20 }), [view, topicId, category]);
  const papersQuery = useInfiniteQuery({
    queryKey: queryKeys.literature.papers(paperFilters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => getLiteraturePapers({ ...paperFilters, cursor: pageParam }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const checkMutation = useMutation({
    mutationFn: () => createLiteratureCheck(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.overview });
      void queryClient.invalidateQueries({ queryKey: queryKeys.literature.checks });
    },
  });
  const papers = papersQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const overview = overviewQuery.data;
  const activeCheck = overview?.active_check;

  const updateSearch = (changes: Record<string, string | null>) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      Object.entries(changes).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
      return next;
    });
  };

  return (
    <PageShell className="p-3">
      <SectionStack gap={4} className="min-h-0">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <SectionHeader eyebrow={t('literature.eyebrow')} title={t('literature.inbox')} description={t('literature.inboxDescription')} />
          <Button variant="secondary" size="sm" onClick={() => updateSearch({ section: section === 'topics' ? null : 'topics' })}>
            <Settings2 className="mr-1 h-4 w-4" />{t('literature.manageTopics')}
          </Button>
        </div>

        {section === 'topics' ? (
          <TopicsPanel onCreate={() => setTopicForForm(null)} onEdit={setTopicForForm} />
        ) : (
          <>
            <SectionCard className="p-4" header={
              <div className="flex flex-wrap items-center gap-2">
                <StatusDot status={checkDot(activeCheck?.status)} />
                <h2 className="text-sm font-semibold text-[var(--text)]">
                  {activeCheck ? t(`literature.checkStatus.${activeCheck.status}`) : t('literature.checkStatus.completed')}
                </h2>
              </div>
            }>
              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <div><p className="text-xs text-[var(--text-tertiary)]">{t('literature.lastChecked')}</p><p className="mt-1 text-[var(--text)]">{formatDate(overview?.last_successful_check_at ?? null, locale)}</p></div>
                <div><p className="text-xs text-[var(--text-tertiary)]">{t('literature.nextCheck')}</p><p className="mt-1 text-[var(--text)]">{formatDate(overview?.next_scheduled_check_at ?? null, locale)}</p></div>
                <div><p className="text-xs text-[var(--text-tertiary)]">{t('literature.unread')}</p><p className="mt-1 text-[var(--text)]">{overview?.counts.unread ?? 0}</p></div>
                <div><p className="text-xs text-[var(--text-tertiary)]">{t('literature.newVersions')}</p><p className="mt-1 text-[var(--text)]">{overview?.counts.updated ?? 0}</p></div>
              </div>
              {activeCheck?.status === 'partial' || activeCheck?.status === 'retrying' ? <Alert variant="warning" className="mt-4">{activeCheck.error ?? t('literature.checkPartial')}</Alert> : null}
              {activeCheck?.status === 'failed' ? <Alert className="mt-4">{activeCheck.error ?? t('literature.checkFailed')}</Alert> : null}
              <div className="mt-4 flex justify-end border-t border-[var(--border)] pt-3">
                <Button size="sm" onClick={() => checkMutation.mutate()} isLoading={checkMutation.isPending || Boolean(activeCheck && ACTIVE_CHECK_STATUSES.has(activeCheck.status))}>
                  <RefreshCw className="mr-1 h-4 w-4" />{t('literature.checkLatest')}
                </Button>
              </div>
            </SectionCard>

            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] pb-3" role="tablist" aria-label={t('literature.inbox')}>
              {VIEWS.map((item) => (
                <button key={item} type="button" role="tab" aria-selected={view === item} onClick={() => updateSearch({ view: item === 'today' ? null : item })}
                  className={view === item ? 'rounded-lg bg-[var(--apple-blue)] px-3 py-1.5 text-xs font-medium text-white' : 'rounded-lg px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-[var(--bg-secondary)]'}>
                  {t(`literature.views.${item}`)}
                </button>
              ))}
              <div className="ml-auto flex flex-wrap gap-2">
                <select aria-label={t('literature.filterTopic')} value={topicId ?? ''} onChange={(event) => updateSearch({ topic: event.target.value || null })} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--text)]">
                  <option value="">{t('literature.allTopics')}</option>
                  {(topicsQuery.data?.items ?? []).map((topic) => <option key={topic.topic_id} value={topic.topic_id}>{topic.label}</option>)}
                </select>
                <select aria-label={t('literature.filterCategory')} value={category ?? ''} onChange={(event) => updateSearch({ category: event.target.value || null })} className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-xs text-[var(--text)]">
                  <option value="">{t('literature.allCategories')}</option>
                  {ARXIV_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </div>
            </div>

            <div className="space-y-3">
              {papersQuery.isLoading && <p className="py-8 text-center text-sm text-[var(--text-secondary)]">{t('common.loading')}</p>}
              {!papersQuery.isLoading && papers.length === 0 && <EmptyState message={t('literature.noPapers')} icon={<BookOpen size={24} />} />}
              {papers.map((paper) => <PaperCard key={paper.paper_id} paper={paper} />)}
              {papersQuery.hasNextPage && <div className="flex justify-center"><Button variant="secondary" size="sm" isLoading={papersQuery.isFetchingNextPage} onClick={() => papersQuery.fetchNextPage()}>{t('literature.loadMore')}</Button></div>}
              {papersQuery.isError && <Alert>{t('literature.loadFailed')}</Alert>}
            </div>
          </>
        )}
      </SectionStack>
      <TopicFormModal key={topicForForm?.topic_id ?? 'new'} isOpen={topicForForm !== undefined} topic={topicForForm ?? null} onClose={() => setTopicForForm(undefined)} />
    </PageShell>
  );
}
