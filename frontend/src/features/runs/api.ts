import { api } from '@/shared/api/client';
import type {
  AttemptListResponse,
  ProjectCostSummary,
  SessionDetailRecord,
  SessionListResponse,
  SessionsBatchDetailResponse,
} from '@/shared/types';

export const getSessions = (params: {
  projectId?: string;
  status?: string;
  cursor?: string;
  limit?: number;
} = {}): Promise<SessionListResponse> => {
  const search = new URLSearchParams();
  if (params.projectId) search.set('project_id', params.projectId);
  if (params.status) search.set('status', params.status);
  if (params.cursor) search.set('cursor', params.cursor);
  if (params.limit) search.set('limit', String(params.limit));
  const query = search.toString();
  return api.get(`/sessions${query ? `?${query}` : ''}`);
};

export const getSessionsBatchDetail = (ids: string[]): Promise<SessionsBatchDetailResponse> =>
  ids.length === 0
    ? Promise.resolve({ items: {} })
    : api.get(`/sessions/batch-detail?ids=${encodeURIComponent(ids.join(','))}`);
export const getSession = (id: string): Promise<SessionDetailRecord> => api.get(`/sessions/${id}`);
export const getAttempts = (sessionId: string): Promise<AttemptListResponse> =>
  api.get(`/sessions/${sessionId}/attempts`);
export const getProjectCostSummary = (projectId: string): Promise<ProjectCostSummary> =>
  api.get(`/projects/${projectId}/cost-summary`);
