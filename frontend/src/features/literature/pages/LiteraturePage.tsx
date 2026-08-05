import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Clock3, ExternalLink, RefreshCw } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  CardBody,
  DetailDrawer,
  EmptyState,
  PageShell,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  StatusBadge,
  type StatusBadgeTone,
} from "@design-system";
import {
  createLiteratureCheck,
  createLiteratureResearchTask,
  getLiteratureOverview,
  getLiteraturePaper,
  getLiteraturePapers,
  getLiteratureResearchTasks,
  getLiteratureSummary,
  getLiteratureTopics,
  requestLiteratureSummary,
  updateLiteraturePaperState,
} from "../api";
import {
  IdempotencyKeyManager,
  semanticMutationValue,
} from "@/shared/api/idempotency";
import { queryKeys } from "@/shared/api/queryKeys";
import type {
  LiteratureCheckStatus,
  LiteratureInboxView,
  LiteraturePaperDetail,
  LiteratureSummary,
  LiteratureTaskIntent,
} from "../types";
import { useLocale, useT } from "@/shared/i18n";

const VIEWS: LiteratureInboxView[] = [
  "today",
  "unread",
  "saved",
  "updated",
  "all",
];
const ALL_FILTER_VALUE = "__all__";
const CATEGORY_OPTIONS = [
  "cs.AI",
  "cs.CL",
  "cs.CV",
  "cs.LG",
  "cs.RO",
  "stat.ML",
];

interface LiteraturePageProps {
  renderTaskCreateFlow: (props: {
    isOpen: boolean;
    initialTitle: string;
    onLiteratureSubmit: (selection: {
      project_id: string;
      workspace_id: string;
      task_preset: string;
      title?: string;
    }) => Promise<void>;
    onClose: () => void;
  }) => ReactNode;
}
const ACTIVE_CHECK_STATUSES = new Set<LiteratureCheckStatus>([
  "planned",
  "checking",
  "partial",
  "retrying",
]);
const ACTIVE_INTENT_STATUSES = new Set([
  "planned",
  "creating_task",
  "task_created",
  "retry_wait",
]);
const POLL_INTERVALS = [5_000, 10_000, 20_000, 30_000];

function progressiveInterval(dataUpdateCount: number): number {
  return POLL_INTERVALS[Math.min(dataUpdateCount, POLL_INTERVALS.length - 1)];
}

function checkStatusTone(
  status: LiteratureCheckStatus | undefined,
): StatusBadgeTone {
  switch (status) {
    case "failed":
      return "danger";
    case "partial":
    case "retrying":
      return "warning";
    case "completed":
      return "success";
    case "planned":
    case "checking":
      return "info";
    default:
      return "neutral";
  }
}

function formatDate(value: string | null, locale: "en" | "zh"): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function PaperDetailSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)] p-4 shadow-[var(--osci-shadow-sm)]">
      <h3 className="text-sm font-semibold text-[var(--osci-color-text)]">{title}</h3>
      {description ? (
        <p className="mt-1 text-xs leading-relaxed text-[var(--osci-color-text-muted)]">
          {description}
        </p>
      ) : null}
      {children}
    </section>
  );
}

function LiteraturePaperDetailContent({
  paper,
  summary,
  researchTasks,
  statePending,
  summaryPending,
  onUpdateState,
  onGenerateSummary,
  onConvertToTask,
}: {
  paper: LiteraturePaperDetail;
  summary: LiteratureSummary | undefined;
  researchTasks: LiteratureTaskIntent[];
  statePending: boolean;
  summaryPending: boolean;
  onUpdateState: (payload: {
    is_read?: boolean;
    is_saved?: boolean;
    is_ignored?: boolean;
  }) => void;
  onGenerateSummary: () => void;
  onConvertToTask: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const summaryInProgress = ["queued", "generating"].includes(summary?.status ?? "");

  return (
    <div
      className="space-y-4 p-4 sm:p-5"
      data-testid="literature-paper-detail-content"
    >
      <section className="rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface-subtle)] p-4">
        <div className="flex flex-wrap gap-2">
          <Badge>{paper.primary_category}</Badge>
          {paper.matched_topics.map((topic) => (
            <Badge key={topic.topic_id} variant="outline">
              {topic.label}
            </Badge>
          ))}
        </div>
        <p className="mt-3 text-sm leading-6 text-[var(--osci-color-text-secondary)]">
          {paper.abstract}
        </p>
        <dl className="mt-4 grid gap-3 border-t border-[var(--osci-color-border-subtle)] pt-4 text-xs min-[460px]:grid-cols-2">
          <div className="min-w-0">
            <dt className="font-medium text-[var(--osci-color-text-muted)]">
              {t("literature.authors")}
            </dt>
            <dd className="mt-1 break-words text-[var(--osci-color-text)]">
              {paper.authors.join(", ")}
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--osci-color-text-muted)]">
              {t("literature.updated")}
            </dt>
            <dd className="mt-1 text-[var(--osci-color-text)]">
              {formatDate(paper.updated_at ?? paper.published_at, locale)}
            </dd>
          </div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-sm">
          <a
            className="inline-flex items-center gap-1.5 font-medium text-[var(--osci-color-primary)] hover:underline"
            href={paper.source_url}
            rel="noreferrer"
            target="_blank"
          >
            {t("literature.viewSource")}
            <ExternalLink aria-hidden="true" size={14} />
          </a>
          <a
            className="inline-flex items-center gap-1.5 font-medium text-[var(--osci-color-primary)] hover:underline"
            href={paper.pdf_url}
            rel="noreferrer"
            target="_blank"
          >
            {t("literature.viewPdf")}
            <ExternalLink aria-hidden="true" size={14} />
          </a>
        </div>
      </section>

      <PaperDetailSection
        title={t("literature.userState")}
        description={t("literature.userStateDescription")}
      >
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusBadge tone={paper.user_state.is_read ? "neutral" : "info"}>
            {paper.user_state.is_read ? t("literature.read") : t("literature.unread")}
          </StatusBadge>
          {paper.user_state.is_saved ? (
            <StatusBadge tone="success">{t("literature.saved")}</StatusBadge>
          ) : null}
          {paper.user_state.is_ignored ? (
            <StatusBadge tone="warning">{t("literature.ignored")}</StatusBadge>
          ) : null}
        </div>
        <div className="mt-4 grid gap-2 min-[460px]:grid-cols-3">
          <Button
            className="w-full"
            size="sm"
            variant="secondary"
            disabled={statePending}
            onClick={() => onUpdateState({ is_read: !paper.user_state.is_read })}
          >
            {paper.user_state.is_read ? t("literature.markUnread") : t("literature.markRead")}
          </Button>
          <Button
            className="w-full"
            size="sm"
            variant="secondary"
            disabled={statePending}
            onClick={() => onUpdateState({ is_saved: !paper.user_state.is_saved })}
          >
            {paper.user_state.is_saved ? t("literature.unsave") : t("literature.savePaper")}
          </Button>
          <Button
            className="w-full"
            size="sm"
            variant="secondary"
            disabled={statePending}
            onClick={() => onUpdateState({ is_ignored: !paper.user_state.is_ignored })}
          >
            {paper.user_state.is_ignored ? t("literature.restore") : t("literature.ignore")}
          </Button>
        </div>
      </PaperDetailSection>

      <PaperDetailSection title={t("literature.versions")}>
        <div className="mt-3 divide-y divide-[var(--osci-color-border-subtle)] rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] px-3">
          {paper.versions.map((version) => (
            <div
              key={version.version_id}
              className="flex items-start justify-between gap-4 py-2.5 text-sm"
            >
              <span className="font-mono font-medium text-[var(--osci-color-text)]">
                {version.provider_version}
              </span>
              <span className="text-right text-xs leading-5 text-[var(--osci-color-text-muted)]">
                {formatDate(version.updated_at ?? version.published_at, locale)}
              </span>
            </div>
          ))}
        </div>
      </PaperDetailSection>

      <PaperDetailSection
        title={t("literature.summary")}
        description={t("literature.summaryDescription")}
      >
        {summary?.status === "completed" && summary.text ? (
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-[var(--osci-color-text-secondary)]">
            {summary.text}
          </p>
        ) : (
          <div className="mt-3">
            {summary?.status === "failed" ? (
              <p className="mb-3 text-sm text-[var(--osci-color-danger-foreground)]">
                {summary.error || t("literature.summaryFailed")}
              </p>
            ) : null}
            <Button
              className="w-full min-[460px]:w-auto"
              size="sm"
              variant="secondary"
              onClick={onGenerateSummary}
              isLoading={summaryPending || summaryInProgress}
            >
              {t("literature.generateSummary")}
            </Button>
          </div>
        )}
      </PaperDetailSection>

      <PaperDetailSection
        title={t("literature.researchTasks")}
        description={t("literature.researchTasksDescription")}
      >
        <Button className="mt-4 w-full" onClick={onConvertToTask}>
          {t("literature.convertToTask")}
        </Button>
        {researchTasks.length > 0 ? (
          <div className="mt-3 space-y-2">
            {researchTasks.map((intent) => (
              <div
                key={intent.intent_id}
                className="rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-3">
                  <StatusBadge
                    tone={
                      intent.status === "completed"
                        ? "success"
                        : intent.status === "failed"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {intent.status}
                  </StatusBadge>
                  {intent.task_id ? (
                    <a
                      className="truncate text-[var(--osci-color-primary)] hover:underline"
                      href={`/tasks?task=${encodeURIComponent(intent.task_id)}`}
                    >
                      {intent.task_id}
                    </a>
                  ) : null}
                </div>
                {intent.last_error ? (
                  <p className="mt-2 text-[var(--osci-color-danger-foreground)]">
                    {intent.last_error}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-3 rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-3 text-sm text-[var(--osci-color-text-muted)]">
            {t("literature.noResearchTasks")}
          </p>
        )}
      </PaperDetailSection>
    </div>
  );
}

export default function LiteraturePage({ renderTaskCreateFlow }: LiteraturePageProps) {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [taskFlowOpen, setTaskFlowOpen] = useState(false);
  const section = searchParams.get("section") === "topics" ? "topics" : "inbox";
  const requestedView = searchParams.get("view");
  const view = VIEWS.includes(requestedView as LiteratureInboxView)
    ? (requestedView as LiteratureInboxView)
    : "today";
  const topicId = searchParams.get("topic") ?? undefined;
  const category = searchParams.get("category") ?? undefined;
  const selectedPaperId = searchParams.get("paper");
  const checkKeyManager = useRef(
    new IdempotencyKeyManager("literature.check.create"),
  ).current;
  const stateKeyManager = useRef(
    new IdempotencyKeyManager("literature.paper.state"),
  ).current;
  const summaryKeyManager = useRef(
    new IdempotencyKeyManager("literature.summary.request"),
  ).current;
  const [researchTaskKeyManager] = useState(
    () => new IdempotencyKeyManager("literature.research-task"),
  );

  const updateSearch = (changes: Record<string, string | null>) =>
    setSearchParams((current) => {
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
    refetchInterval: (query) =>
      ACTIVE_CHECK_STATUSES.has(
        query.state.data?.active_check?.status ?? "completed",
      )
        ? progressiveInterval(query.state.dataUpdateCount)
        : false,
  });
  const topicsQuery = useQuery({
    queryKey: queryKeys.literature.topics,
    queryFn: getLiteratureTopics,
  });
  const paperFilters = useMemo(
    () => ({ view, topic_id: topicId, category, limit: 30 }),
    [category, topicId, view],
  );
  const papersQuery = useInfiniteQuery({
    queryKey: queryKeys.literature.papers(paperFilters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      getLiteraturePapers({ ...paperFilters, cursor: pageParam }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const paperQuery = useQuery({
    queryKey: queryKeys.literature.paper(selectedPaperId),
    queryFn: () => getLiteraturePaper(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
  });
  const summaryQuery = useQuery({
    queryKey: queryKeys.literature.summary(selectedPaperId),
    queryFn: () => getLiteratureSummary(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: (query) =>
      ["queued", "generating"].includes(query.state.data?.status ?? "")
        ? progressiveInterval(query.state.dataUpdateCount)
        : false,
  });
  const researchTasksQuery = useQuery({
    queryKey: queryKeys.literature.researchTasks(selectedPaperId),
    queryFn: () => getLiteratureResearchTasks(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ACTIVE_INTENT_STATUSES.has(item.status),
      )
        ? progressiveInterval(query.state.dataUpdateCount)
        : false,
  });

  const checkMutation = useMutation({
    mutationFn: (idempotencyKey: string) =>
      createLiteratureCheck(idempotencyKey),
    onSuccess: (_check, idempotencyKey) => {
      checkKeyManager.markSucceeded(idempotencyKey);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.literature.overview,
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.literature.checks,
      });
    },
  });
  const stateMutation = useMutation({
    mutationFn: ({
      paperId,
      payload,
      idempotencyKey,
    }: {
      paperId: string;
      payload: { is_read?: boolean; is_saved?: boolean; is_ignored?: boolean };
      idempotencyKey: string;
    }) => updateLiteraturePaperState(paperId, payload, idempotencyKey),
    onSuccess: (_paper, variables) => {
      stateKeyManager.markSucceeded(variables.idempotencyKey);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.literature.all,
      });
    },
  });
  const summaryMutation = useMutation({
    mutationFn: ({
      paperId,
      language,
      idempotencyKey,
    }: {
      paperId: string;
      language: string;
      idempotencyKey: string;
    }) => requestLiteratureSummary(paperId, idempotencyKey, language),
    onSuccess: (summary, variables) => {
      summaryKeyManager.markSucceeded(variables.idempotencyKey);
      queryClient.setQueryData(
        queryKeys.literature.summary(variables.paperId),
        summary,
      );
    },
  });
  const startCheck = () => {
    const semantic = semanticMutationValue({ topicIds: null });
    checkMutation.mutate(checkKeyManager.keyFor(semantic));
  };
  const updatePaperState = (
    paperId: string,
    payload: { is_read?: boolean; is_saved?: boolean; is_ignored?: boolean },
  ) => {
    const semantic = semanticMutationValue({ paperId, payload });
    stateMutation.mutate({
      paperId,
      payload,
      idempotencyKey: stateKeyManager.keyFor(semantic),
    });
  };
  const generateSummary = () => {
    if (!selectedPaperId) return;
    const language = locale === "zh" ? "zh" : "en";
    const semantic = semanticMutationValue({
      paperId: selectedPaperId,
      language,
    });
    summaryMutation.mutate({
      paperId: selectedPaperId,
      language,
      idempotencyKey: summaryKeyManager.keyFor(semantic),
    });
  };
  const papers = papersQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const overview = overviewQuery.data;
  const activeCheck = overview?.active_check;
  const checkTone = checkStatusTone(activeCheck?.status);

  const submitResearchTask = async (selection: {
    project_id: string;
    workspace_id: string;
    task_preset: string;
    title?: string;
  }) => {
    if (!selectedPaperId) return;
    const semantic = semanticMutationValue({ paperId: selectedPaperId, selection });
    const key = researchTaskKeyManager.keyFor(semantic);
    await createLiteratureResearchTask(
      selectedPaperId,
      selection,
      key,
    );
    researchTaskKeyManager.markSucceeded(key);
    void queryClient.invalidateQueries({
      queryKey: queryKeys.literature.researchTasks(selectedPaperId),
    });
  };

  return (
    <PageShell variant="canvas">
      <div className="mx-auto flex w-full max-w-[1450px] flex-col gap-4 p-4 md:p-6">
        <header className="flex flex-wrap items-end justify-between gap-x-5 gap-y-3">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--osci-color-primary)]">
              {t("literature.eyebrow")}
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--osci-color-text)]">
              {t("literature.inbox")}
            </h1>
          </div>
          <Button
            size="sm"
            className="shrink-0 gap-1.5"
            onClick={startCheck}
            isLoading={
              checkMutation.isPending ||
              Boolean(
                activeCheck && ACTIVE_CHECK_STATUSES.has(activeCheck.status),
              )
            }
          >
            <RefreshCw aria-hidden="true" size={14} />
            {t("literature.checkLatest")}
          </Button>
        </header>

        <section
          className="overflow-hidden rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)] shadow-[var(--osci-shadow-sm)]"
          data-testid="literature-controls"
        >
          <div className="flex min-w-0 flex-wrap items-center gap-2 p-2.5">
            <div className="flex shrink-0 items-center gap-1 rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-0.5">
              <Button
                size="sm"
                className="min-h-7 px-2.5"
                variant={section === "inbox" ? "primary" : "ghost"}
                onClick={() => updateSearch({ section: null })}
              >
                {t("literature.inboxSection")}
              </Button>
              <Button
                size="sm"
                className="min-h-7 px-2.5"
                variant={section === "topics" ? "primary" : "ghost"}
                onClick={() => updateSearch({ section: "topics" })}
              >
                {t("literature.manageTopics")}
              </Button>
            </div>
            {section === "inbox" ? (
              <nav
                aria-label={t("literature.inboxViews")}
                className="min-w-0 flex-1 overflow-x-auto"
              >
                <div className="flex w-max min-w-full items-center gap-1">
                  {VIEWS.map((item) => {
                    const count =
                      item === "all" ? undefined : overview?.counts[item];
                    return (
                      <Button
                        key={item}
                        size="sm"
                        className="min-h-7 whitespace-nowrap px-2.5"
                        variant={view === item ? "secondary" : "ghost"}
                        onClick={() =>
                          updateSearch({ view: item === "today" ? null : item })
                        }
                      >
                        {t(`literature.views.${item}`)}
                        {count !== undefined ? (
                          <span
                            aria-hidden="true"
                            className="ml-1.5 rounded-full bg-[var(--osci-color-surface-subtle)] px-1.5 py-0.5 text-[10px] leading-none tabular-nums text-[var(--osci-color-text-muted)]"
                          >
                            {count}
                          </span>
                        ) : null}
                      </Button>
                    );
                  })}
                </div>
              </nav>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface-subtle)]/45 px-2.5 py-2">
            <div
              className="flex min-w-0 flex-1 items-center gap-2 text-xs text-[var(--osci-color-text)]"
              data-testid="literature-check-status"
            >
              <Clock3
                aria-hidden="true"
                className="shrink-0 text-[var(--osci-color-text-muted)]"
                size={14}
              />
              <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                <span className="whitespace-nowrap">
                  <span className="text-[var(--osci-color-text-muted)]">
                    {t("literature.lastChecked")}
                  </span>{" "}
                  <span className="font-medium tabular-nums">
                    {formatDate(overview?.last_successful_check_at ?? null, locale)}
                  </span>
                </span>
                <span className="whitespace-nowrap">
                  <span className="text-[var(--osci-color-text-muted)]">
                    {t("literature.nextCheck")}
                  </span>{" "}
                  <span className="font-medium tabular-nums">
                    {formatDate(overview?.next_scheduled_check_at ?? null, locale)}
                  </span>
                </span>
                {activeCheck ? (
                  <StatusBadge tone={checkTone}>
                    {t(`literature.checkStatus.${activeCheck.status}`)}
                  </StatusBadge>
                ) : null}
                {activeCheck?.error ? (
                  <span className="min-w-0 truncate text-[var(--osci-color-danger-foreground)]">
                    {activeCheck.error}
                  </span>
                ) : null}
              </div>
            </div>

            {section === "inbox" ? (
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Select
                  value={topicId ?? ALL_FILTER_VALUE}
                  onValueChange={(value) =>
                    updateSearch({
                      topic: value === ALL_FILTER_VALUE ? null : value,
                    })
                  }
                >
                  <SelectTrigger
                    aria-label={t("literature.filterTopic")}
                    className="min-h-8 w-[9.5rem] px-2.5 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_FILTER_VALUE}>
                      {t("literature.allTopics")}
                    </SelectItem>
                    {(topicsQuery.data?.items ?? []).map((topic) => (
                      <SelectItem key={topic.topic_id} value={topic.topic_id}>
                        {topic.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={category ?? ALL_FILTER_VALUE}
                  onValueChange={(value) =>
                    updateSearch({
                      category: value === ALL_FILTER_VALUE ? null : value,
                    })
                  }
                >
                  <SelectTrigger
                    aria-label={t("literature.filterCategory")}
                    className="min-h-8 w-[8.75rem] px-2.5 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_FILTER_VALUE}>
                      {t("literature.allCategories")}
                    </SelectItem>
                    {CATEGORY_OPTIONS.map((item) => (
                      <SelectItem key={item} value={item}>
                        {item}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </div>
        </section>

        {section === "topics" ? (
          <Card>
            <CardBody className="space-y-3 p-5">
              {(topicsQuery.data?.items ?? []).map((topic) => (
                <div
                  key={topic.topic_id}
                  className="rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3"
                >
                  <div className="flex items-center gap-2">
                    <h2 className="font-semibold text-[var(--osci-color-text)]">
                      {topic.label}
                    </h2>
                    <StatusBadge tone={topic.is_active ? "success" : "neutral"}>
                      {topic.is_active ? "active" : "paused"}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 text-sm text-[var(--osci-color-text-secondary)]">
                    {topic.categories.join(" · ")} ·{" "}
                    {topic.include_terms.join(", ")}
                  </p>
                </div>
              ))}
              {!topicsQuery.isLoading &&
              (topicsQuery.data?.items.length ?? 0) === 0 ? (
                <EmptyState message={t("literature.noTopics")} />
              ) : null}
            </CardBody>
          </Card>
        ) : (
          <Card>
            <CardBody className="divide-y divide-[var(--osci-color-border-subtle)] p-0">
              {papers.map((paper) => (
                <article
                  key={paper.paper_id}
                  className="flex flex-col gap-3 p-4 md:flex-row md:items-start md:justify-between"
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => updateSearch({ paper: paper.paper_id })}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{paper.primary_category}</Badge>
                      {!paper.user_state.is_read ? (
                        <Badge variant="secondary">
                          {t("literature.newPaper")}
                        </Badge>
                      ) : null}
                      {paper.user_state.is_saved ? (
                        <Badge variant="outline">{t("literature.saved")}</Badge>
                      ) : null}
                      {paper.matched_topics.map((topic) => (
                        <Badge key={topic.topic_id} variant="outline">
                          {topic.label}
                        </Badge>
                      ))}
                    </div>
                    <h2 className="mt-2 font-semibold text-[var(--osci-color-text)]">
                      {paper.title}
                    </h2>
                    <p className="mt-1 text-xs text-[var(--osci-color-text-muted)]">
                      {paper.authors.join(", ")} ·{" "}
                      {formatDate(
                        paper.updated_at ?? paper.published_at,
                        locale,
                      )}
                    </p>
                    <p className="mt-2 line-clamp-2 text-sm text-[var(--osci-color-text-secondary)]">
                      {paper.abstract}
                    </p>
                  </button>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        updatePaperState(paper.paper_id, {
                          is_read: !paper.user_state.is_read,
                        })
                      }
                    >
                      {paper.user_state.is_read
                        ? t("literature.markUnread")
                        : t("literature.markRead")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() =>
                        updatePaperState(paper.paper_id, {
                          is_saved: !paper.user_state.is_saved,
                        })
                      }
                    >
                      {paper.user_state.is_saved
                        ? t("literature.unsave")
                        : t("literature.savePaper")}
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => updateSearch({ paper: paper.paper_id })}
                    >
                      {t("literature.details")}
                    </Button>
                  </div>
                </article>
              ))}
              {!papersQuery.isLoading && papers.length === 0 ? (
                <EmptyState message={t("literature.noPapers")} />
              ) : null}
              {papersQuery.hasNextPage ? (
                <div className="flex justify-center p-4">
                  <Button
                    variant="secondary"
                    onClick={() => papersQuery.fetchNextPage()}
                    isLoading={papersQuery.isFetchingNextPage}
                  >
                    {t("literature.loadMore")}
                  </Button>
                </div>
              ) : null}
            </CardBody>
          </Card>
        )}
      </div>

      <DetailDrawer
        open={Boolean(selectedPaperId)}
        onOpenChange={(open) => {
          if (!open) updateSearch({ paper: null });
        }}
        title={paperQuery.data?.title ?? t("literature.paperDetails")}
        closeLabel={t("components.modal.close")}
        className="!w-[min(34rem,calc(100%-1rem))]"
      >
        {paperQuery.data ? (
          <LiteraturePaperDetailContent
            paper={paperQuery.data}
            summary={summaryQuery.data}
            researchTasks={researchTasksQuery.data?.items ?? []}
            statePending={stateMutation.isPending}
            summaryPending={summaryMutation.isPending}
            onUpdateState={(payload) => updatePaperState(paperQuery.data.paper_id, payload)}
            onGenerateSummary={generateSummary}
            onConvertToTask={() => setTaskFlowOpen(true)}
          />
        ) : null}
      </DetailDrawer>
      {renderTaskCreateFlow({
        isOpen: taskFlowOpen,
        initialTitle: paperQuery.data?.title ? `Research: ${paperQuery.data.title}` : "",
        onLiteratureSubmit: submitResearchTask,
        onClose: () => setTaskFlowOpen(false),
      })}
    </PageShell>
  );
}
