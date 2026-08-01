import { api } from '@/shared/api/client';
import type {
  LiteratureCheck,
  LiteratureOverview,
  LiteraturePaperDetail,
  LiteraturePaperListParams,
  LiteraturePaperListResponse,
  LiteratureSummary,
  LiteratureTaskIntent,
  LiteratureTopic,
  LiteratureTopicInput,
  LiteratureTopicPreview,
} from '@/shared/types';

function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

export const getLiteratureOverview = (): Promise<LiteratureOverview> =>
  api.get('/literature/overview');
export const getLiteratureTopics = (): Promise<{ items: LiteratureTopic[] }> =>
  api.get('/literature/topics');
export const createLiteratureTopic = (payload: LiteratureTopicInput): Promise<LiteratureTopic> =>
  api.post('/literature/topics', payload);
export const updateLiteratureTopic = (
  topicId: string,
  payload: Partial<LiteratureTopicInput & Pick<LiteratureTopic, 'is_active'>>,
): Promise<LiteratureTopic> => api.patch(`/literature/topics/${topicId}`, payload);
export const deleteLiteratureTopic = (topicId: string): Promise<void> =>
  api.delete(`/literature/topics/${topicId}`);
export const previewLiteratureTopic = (payload: LiteratureTopicInput): Promise<LiteratureTopicPreview> =>
  api.post('/literature/topics/preview', payload);

export const getLiteraturePapers = (
  params: LiteraturePaperListParams = {},
): Promise<LiteraturePaperListResponse> => api.get(`/literature/papers${queryString({
  view: params.view,
  topic_id: params.topic_id,
  category: params.category,
  cursor: params.cursor,
  limit: params.limit,
})}`);
export const getLiteraturePaper = (paperId: string): Promise<LiteraturePaperDetail> =>
  api.get(`/literature/papers/${paperId}`);
export const updateLiteraturePaperState = (
  paperId: string,
  payload: Partial<Pick<LiteraturePaperDetail['user_state'], 'is_read' | 'is_saved' | 'is_ignored'>>,
  idempotencyKey: string,
): Promise<LiteraturePaperDetail> => api.patch(`/literature/papers/${paperId}/state`, payload, {
  headers: { 'Idempotency-Key': idempotencyKey },
});
export const getLiteratureSummary = (paperId: string): Promise<LiteratureSummary> =>
  api.get(`/literature/papers/${paperId}/summary`);
export const requestLiteratureSummary = (
  paperId: string,
  idempotencyKey: string,
  language = 'zh',
): Promise<LiteratureSummary> => api.post(`/literature/papers/${paperId}/summary`, { language }, {
  headers: { 'Idempotency-Key': idempotencyKey },
});
export const createLiteratureCheck = (
  idempotencyKey: string,
  topicIds?: string[],
): Promise<LiteratureCheck> => api.post('/literature/checks', topicIds ? { topic_ids: topicIds } : {}, {
  headers: { 'Idempotency-Key': idempotencyKey },
});
export const getCurrentLiteratureCheck = (): Promise<LiteratureCheck | null> =>
  api.get('/literature/checks/current');
export const getLiteratureChecks = (limit = 30): Promise<{ items: LiteratureCheck[] }> =>
  api.get(`/literature/checks${queryString({ limit })}`);
export const getLiteratureCheck = (checkId: string): Promise<LiteratureCheck> =>
  api.get(`/literature/checks/${checkId}`);
export const createLiteratureResearchTask = (
  paperId: string,
  payload: { project_id: string; workspace_id: string; task_preset: string; title?: string },
  idempotencyKey: string,
): Promise<LiteratureTaskIntent> => api.post(
  `/literature/papers/${encodeURIComponent(paperId)}/research-task`,
  payload,
  { headers: { 'Idempotency-Key': idempotencyKey } },
);
export const getLiteratureResearchTask = (
  paperId: string,
  idempotencyKey: string,
): Promise<LiteratureTaskIntent> => api.get(
  `/literature/papers/${encodeURIComponent(paperId)}/research-task?idempotency_key=${encodeURIComponent(idempotencyKey)}`,
);
export const getLiteratureResearchTasks = (
  paperId: string,
): Promise<{ items: LiteratureTaskIntent[] }> =>
  api.get(`/literature/papers/${encodeURIComponent(paperId)}/research-tasks`);
