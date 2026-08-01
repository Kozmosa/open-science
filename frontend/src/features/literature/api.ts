import { api } from "@/shared/api/client";
import { transportPath } from "@/shared/api/transport";
import type {
  LiteratureCheckListResponse as CheckListTransport,
  LiteratureCheckRequest,
  LiteratureCheckResponse as CheckTransport,
  LiteratureOverviewResponse as OverviewTransport,
  LiteraturePaperDetailResponse as PaperDetailTransport,
  LiteraturePaperListResponse as PaperListTransport,
  LiteraturePaperStateRequest,
  LiteratureResearchTaskListResponse as TaskListTransport,
  LiteratureResearchTaskRequest,
  LiteratureResearchTaskResponse as TaskTransport,
  LiteratureSummaryRequest,
  LiteratureSummaryResponse as SummaryTransport,
  LiteratureTopicListResponse as TopicListTransport,
  LiteratureTopicPreviewResponse as TopicPreviewTransport,
  LiteratureTopicRequest,
  LiteratureTopicResponse as TopicTransport,
  LiteratureTopicUpdateRequest,
} from "@/generated/transport";
import {
  adaptCheck,
  adaptCheckList,
  adaptOverview,
  adaptPaper,
  adaptPaperList,
  adaptSummary,
  adaptTask,
  adaptTaskList,
  adaptTopic,
  adaptTopicList,
  adaptTopicPreview,
} from "./adapter";
import type {
  LiteratureCheck,
  LiteratureList,
  LiteratureOverview,
  LiteraturePaperDetail,
  LiteraturePaperListParams,
  LiteraturePaperListResponse,
  LiteratureSummary,
  LiteratureTaskIntent,
  LiteratureTopic,
  LiteratureTopicInput,
  LiteratureTopicPreview,
} from "./types";

function queryString(
  params: Record<string, string | number | boolean | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined) search.set(key, String(value));
  const query = search.toString();
  return query ? `?${query}` : "";
}

export const getLiteratureOverview = async (): Promise<LiteratureOverview> =>
  adaptOverview(
    await api.get<OverviewTransport>(
      transportPath("get_api_literature_overview"),
    ),
  );
export const getLiteratureTopics = async (): Promise<
  LiteratureList<LiteratureTopic>
> =>
  adaptTopicList(
    await api.get<TopicListTransport>(
      transportPath("get_api_literature_topics"),
    ),
  );
export const createLiteratureTopic = async (
  payload: LiteratureTopicInput,
): Promise<LiteratureTopic> =>
  adaptTopic(
    await api.post<TopicTransport>(
      transportPath("post_api_literature_topics"),
      payload satisfies LiteratureTopicRequest,
    ),
  );
export const updateLiteratureTopic = async (
  topicId: string,
  payload: LiteratureTopicUpdateRequest,
): Promise<LiteratureTopic> =>
  adaptTopic(
    await api.patch<TopicTransport>(
      transportPath("patch_api_literature_topics_topic_id", {
        topic_id: topicId,
      }),
      payload,
    ),
  );
export const deleteLiteratureTopic = (topicId: string): Promise<void> =>
  api.delete(
    transportPath("delete_api_literature_topics_topic_id", {
      topic_id: topicId,
    }),
  );
export const previewLiteratureTopic = async (
  payload: LiteratureTopicInput,
): Promise<LiteratureTopicPreview> =>
  adaptTopicPreview(
    await api.post<TopicPreviewTransport>(
      transportPath("post_api_literature_topics_preview"),
      payload satisfies LiteratureTopicRequest,
    ),
  );

export const getLiteraturePapers = async (
  params: LiteraturePaperListParams = {},
): Promise<LiteraturePaperListResponse> =>
  adaptPaperList(
    await api.get<PaperListTransport>(
      `${transportPath("get_api_literature_papers")}${queryString({ view: params.view, topic_id: params.topic_id, category: params.category, summary_status: params.summary_status, has_research_task: params.has_research_task, cursor: params.cursor, limit: params.limit })}`,
    ),
  );
export const getLiteraturePaper = async (
  paperId: string,
): Promise<LiteraturePaperDetail> =>
  adaptPaper(
    await api.get<PaperDetailTransport>(
      transportPath("get_api_literature_papers_paper_id", {
        paper_id: paperId,
      }),
    ),
  );
export const updateLiteraturePaperState = async (
  paperId: string,
  payload: LiteraturePaperStateRequest,
  idempotencyKey: string,
): Promise<LiteraturePaperDetail> =>
  adaptPaper(
    await api.patch<PaperDetailTransport>(
      transportPath("patch_api_literature_papers_paper_id_state", {
        paper_id: paperId,
      }),
      payload,
      { headers: { "Idempotency-Key": idempotencyKey } },
    ),
  );
export const getLiteratureSummary = async (
  paperId: string,
): Promise<LiteratureSummary> =>
  adaptSummary(
    await api.get<SummaryTransport>(
      transportPath("get_api_literature_papers_paper_id_summary", {
        paper_id: paperId,
      }),
    ),
  );
export const requestLiteratureSummary = async (
  paperId: string,
  idempotencyKey: string,
  language = "zh",
): Promise<LiteratureSummary> =>
  adaptSummary(
    await api.post<SummaryTransport>(
      transportPath("post_api_literature_papers_paper_id_summary", {
        paper_id: paperId,
      }),
      { language } satisfies LiteratureSummaryRequest,
      { headers: { "Idempotency-Key": idempotencyKey } },
    ),
  );
export const createLiteratureCheck = async (
  idempotencyKey: string,
  topicIds?: string[],
): Promise<LiteratureCheck> =>
  adaptCheck(
    await api.post<CheckTransport>(
      transportPath("post_api_literature_checks"),
      { topic_ids: topicIds ?? null } satisfies LiteratureCheckRequest,
      { headers: { "Idempotency-Key": idempotencyKey } },
    ),
  );
export const getCurrentLiteratureCheck =
  async (): Promise<LiteratureCheck | null> => {
    const value = await api.get<CheckTransport | null>(
      transportPath("get_api_literature_checks_current"),
    );
    return value ? adaptCheck(value) : null;
  };
export const getLiteratureChecks = async (
  limit = 30,
): Promise<LiteratureList<LiteratureCheck>> =>
  adaptCheckList(
    await api.get<CheckListTransport>(
      `${transportPath("get_api_literature_checks")}${queryString({ limit })}`,
    ),
  );
export const getLiteratureCheck = async (
  checkId: string,
): Promise<LiteratureCheck> =>
  adaptCheck(
    await api.get<CheckTransport>(
      transportPath("get_api_literature_checks_check_id", {
        check_id: checkId,
      }),
    ),
  );
export const createLiteratureResearchTask = async (
  paperId: string,
  payload: LiteratureResearchTaskRequest,
  idempotencyKey: string,
): Promise<LiteratureTaskIntent> =>
  adaptTask(
    await api.post<TaskTransport>(
      transportPath("post_api_literature_papers_paper_id_research_task", {
        paper_id: paperId,
      }),
      payload,
      { headers: { "Idempotency-Key": idempotencyKey } },
    ),
  );
export const getLiteratureResearchTasks = async (
  paperId: string,
): Promise<LiteratureList<LiteratureTaskIntent>> =>
  adaptTaskList(
    await api.get<TaskListTransport>(
      transportPath("get_api_literature_papers_paper_id_research_tasks", {
        paper_id: paperId,
      }),
    ),
  );
