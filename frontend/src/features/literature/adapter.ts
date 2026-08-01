import type {
  LiteratureCheckListResponse as CheckListTransport,
  LiteratureCheckResponse as CheckTransport,
  LiteratureOverviewResponse as OverviewTransport,
  LiteraturePaperDetailResponse as PaperDetailTransport,
  LiteraturePaperListResponse as PaperListTransport,
  LiteratureResearchTaskListResponse as TaskListTransport,
  LiteratureResearchTaskResponse as TaskTransport,
  LiteratureSummaryResponse as SummaryTransport,
  LiteratureTopicListResponse as TopicListTransport,
  LiteratureTopicPreviewResponse as TopicPreviewTransport,
  LiteratureTopicResponse as TopicTransport,
} from "@/generated/transport";
import type {
  LiteratureCheck,
  LiteratureList,
  LiteratureOverview,
  LiteraturePaperDetail,
  LiteraturePaperListResponse,
  LiteratureSummary,
  LiteratureTaskIntent,
  LiteratureTopic,
  LiteratureTopicPreview,
} from "./types";

const nullable = <T>(value: T | null | undefined): T | null => value ?? null;

export const adaptTopic = (value: TopicTransport): LiteratureTopic => ({
  ...value,
  last_matched_at: nullable(value.last_matched_at),
});
export const adaptTopicList = (
  value: TopicListTransport,
): LiteratureList<LiteratureTopic> => ({
  items: value.items.map(adaptTopic),
  total: value.total,
  next_cursor: nullable(value.next_cursor),
});
export const adaptTopicPreview = (
  value: TopicPreviewTransport,
): LiteratureTopicPreview => ({ ...value });
export const adaptCheck = (value: CheckTransport): LiteratureCheck => ({
  ...value,
  window_start: nullable(value.window_start),
  window_end: nullable(value.window_end),
  started_at: nullable(value.started_at),
  completed_at: nullable(value.completed_at),
  next_attempt_at: nullable(value.next_attempt_at),
  error: nullable(value.error),
});
export const adaptCheckList = (
  value: CheckListTransport,
): LiteratureList<LiteratureCheck> => ({
  items: value.items.map(adaptCheck),
  total: value.total,
  next_cursor: nullable(value.next_cursor),
});
export const adaptOverview = (
  value: OverviewTransport,
): LiteratureOverview => ({
  ...value,
  active_check: value.active_check ? adaptCheck(value.active_check) : null,
});
export const adaptPaper = (
  value: PaperDetailTransport,
): LiteraturePaperDetail => ({
  ...value,
  published_at: nullable(value.published_at),
  updated_at: nullable(value.updated_at),
  current_version_id: nullable(value.current_version_id),
  versions: value.versions.map((version) => ({
    ...version,
    published_at: nullable(version.published_at),
    updated_at: nullable(version.updated_at),
  })),
});
export const adaptPaperList = (
  value: PaperListTransport,
): LiteraturePaperListResponse => ({
  items: value.items.map((paper) => ({
    ...paper,
    published_at: nullable(paper.published_at),
    updated_at: nullable(paper.updated_at),
    current_version_id: nullable(paper.current_version_id),
  })),
  total: value.total,
  next_cursor: nullable(value.next_cursor),
});
export const adaptSummary = (value: SummaryTransport): LiteratureSummary => ({
  summary_id: nullable(value.summary_id),
  status: value.status,
  text: nullable(value.text),
  practice_note: nullable(value.practice_note),
  error: nullable(value.error),
  version_id: nullable(value.version_id),
});
export const adaptTask = (value: TaskTransport): LiteratureTaskIntent => ({
  ...value,
  task_id: nullable(value.task_id),
  last_error: nullable(value.last_error),
  next_retry_at: nullable(value.next_retry_at),
  heartbeat_at: nullable(value.heartbeat_at),
  completed_at: nullable(value.completed_at),
});
export const adaptTaskList = (
  value: TaskListTransport,
): LiteratureList<LiteratureTaskIntent> => ({
  items: value.items.map(adaptTask),
  total: value.total,
  next_cursor: nullable(value.next_cursor),
});
