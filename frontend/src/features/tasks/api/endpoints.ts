import { api } from '@/shared/api/client';
import type {
  TaskEdge,
  TaskEdgeListResponse,
  TaskListResponse,
  TaskMessagesResponse,
  TaskOutputListResponse,
  TaskRecord,
  TaskSummary,
  TaskStatus,
  TaskTokenUsageSummary,
} from '@/shared/types';
import type {
  TaskCreatePayload,
  TaskMutationResponse,
  TaskPauseResponse,
  TaskRelationshipCreateRequest,
  TaskRelationshipListResponse,
  TaskRelationshipResponse,
  TaskResumeResponse,
} from '@/shared/api/transportTypes';

const API_BASE = '/api';
const API_KEY = import.meta.env.VITE_OPENSCIENCE_API_KEY?.trim()
  || import.meta.env.VITE_AINRF_API_KEY?.trim()
  || '';

const TASK_STATUSES = new Set<TaskStatus>([
  'queued', 'starting', 'running', 'succeeded', 'failed', 'cancelled', 'paused',
  'launch_unknown', 'stopped_by_project_archive', 'stopped_permission_revoked',
  'stopped_runtime_unknown',
]);

function mutationTask(response: TaskMutationResponse): TaskSummary {
  if (!TASK_STATUSES.has(response.task.status as TaskStatus)) {
    throw new Error(`Unknown Task status: ${response.task.status}`);
  }
  return {
    ...response.task,
    status: response.task.status as TaskStatus,
    started_at: response.task.started_at ?? null,
    completed_at: response.task.completed_at ?? null,
    error_summary: response.task.error_summary ?? null,
  };
}

export const getTasks = (params: {
  includeArchived?: boolean;
  projectId?: string;
  limit?: number;
  sort?: 'updated' | 'created' | 'name';
} = {}): Promise<TaskListResponse> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? false) });
  if (params.projectId) search.set('project_id', params.projectId);
  if (params.limit) search.set('limit', String(params.limit));
  if (params.sort) search.set('sort', params.sort);
  return api.get(`/tasks?${search.toString()}`);
};

export const getTask = (taskId: string): Promise<TaskRecord> => api.get(`/tasks/${taskId}`);

export const getTaskTokenUsageSummary = (
  params: { includeArchived?: boolean } = {},
): Promise<TaskTokenUsageSummary> => {
  const search = new URLSearchParams({
    include_archived: String(params.includeArchived ?? true),
  });
  return api.get(`/tasks/token-usage?${search.toString()}`);
};

export const createTask = async (
  payload: TaskCreatePayload,
  idempotencyKey: string,
): Promise<TaskSummary> => {
  const response = await api.post<TaskMutationResponse>('/tasks', payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
  return mutationTask(response);
};

function taskAction(taskId: string, action: string, idempotencyKey: string): Promise<TaskSummary> {
  return api.post(`/tasks/${taskId}/${action}`, {}, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
}

export const archiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'archive', key);
export const unarchiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'unarchive', key);
export const cancelTask = (taskId: string, key: string): Promise<void> =>
  api.post(`/tasks/${taskId}/cancel`, {}, { headers: { 'Idempotency-Key': key } });
export const pauseTask = (taskId: string, key: string): Promise<TaskPauseResponse> =>
  api.post(`/tasks/${taskId}/pause`, {}, { headers: { 'Idempotency-Key': key } });
export const resumeTask = (taskId: string, key: string): Promise<TaskResumeResponse> =>
  api.post(`/tasks/${taskId}/resume`, {}, { headers: { 'Idempotency-Key': key } });

export const deleteTask = (taskId: string): Promise<void> => api.delete(`/tasks/${taskId}/permanent`);
export const retryTask = async (taskId: string, key: string): Promise<TaskSummary> => {
  const response = await api.post<TaskMutationResponse>(`/tasks/${taskId}/retry`, undefined, {
    headers: { 'Idempotency-Key': key },
  });
  return mutationTask(response);
};

export const moveTask = (
  taskId: string,
  payload: { project_id: string; context_version_id: string },
  key: string,
): Promise<TaskSummary> => api.post(`/tasks/${taskId}/move`, payload, {
  headers: { 'Idempotency-Key': key },
});

export const forkTask = async (
  taskId: string,
  payload: { workspace_id: string; project_id?: string; prompt?: string; title?: string },
  key: string,
): Promise<TaskSummary> => {
  const response = await api.post<TaskMutationResponse>(`/tasks/${taskId}/fork`, payload, {
    headers: { 'Idempotency-Key': key },
  });
  return mutationTask(response);
};

export const updateTask = (
  taskId: string,
  data: { title?: string },
  key: string,
): Promise<TaskSummary> => api.patch(`/tasks/${taskId}`, data, {
  headers: { 'Idempotency-Key': key },
});

export const getProjectTasks = (
  projectId: string,
  params: { includeArchived?: boolean; limit?: number } = {},
): Promise<TaskListResponse> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? false) });
  search.set('project_id', projectId);
  if (params.limit) search.set('limit', String(params.limit));
  return api.get(`/tasks?${search.toString()}`);
};

const relationshipToTaskEdge = (relationship: TaskRelationshipResponse): TaskEdge => ({
  edge_id: relationship.relationship_id,
  project_id: relationship.project_id,
  source_task_id: relationship.source_task_id,
  target_task_id: relationship.target_task_id,
  relationship_type: relationship.relationship_type ?? 'related_to',
  created_at: relationship.created_at,
});

export const getTaskEdges = async (projectId: string): Promise<TaskEdgeListResponse> => {
  const response = await api.get<TaskRelationshipListResponse>(
    `/domain/projects/${projectId}/task-relationships`,
  );
  return { items: response.items.map(relationshipToTaskEdge) };
};
export const createTaskEdge = async (
  projectId: string,
  payload: TaskRelationshipCreateRequest,
  key: string,
): Promise<TaskEdge> => {
  const response = await api.post<TaskRelationshipResponse>(
    `/domain/projects/${projectId}/task-relationships`,
    payload,
    { headers: { 'Idempotency-Key': key } },
  );
  return relationshipToTaskEdge(response);
};
export const deleteTaskEdge = (
  projectId: string,
  relationshipId: string,
  key: string,
): Promise<void> => api.delete(
  `/domain/projects/${projectId}/task-relationships/${relationshipId}`,
  { headers: { 'Idempotency-Key': key } },
);

export const getTaskOutput = (
  taskId: string,
  afterSeq = 0,
  limit = 0,
): Promise<TaskOutputListResponse> => api.get(
  `/tasks/${taskId}/output?after_seq=${afterSeq}${limit > 0 ? `&limit=${limit}` : ''}`,
);

export const buildTaskStreamUrl = (taskId: string, afterSeq = 0): string => {
  const search = new URLSearchParams({ after_seq: String(afterSeq) });
  if (API_KEY) search.set('api_key', API_KEY);
  return `${API_BASE}/tasks/${taskId}/stream?${search.toString()}`;
};

export const sendTaskPrompt = (
  taskId: string,
  prompt: string,
  key: string,
): Promise<{ task_id: string; sequence: number }> => api.post(
  `/tasks/${taskId}/continue`,
  { prompt },
  { headers: { 'Idempotency-Key': key } },
);

export const getTaskMessages = (
  taskId: string,
  afterSeq = 0,
  limit = 100,
): Promise<TaskMessagesResponse> =>
  api.get(`/tasks/${taskId}/messages?after_seq=${afterSeq}&limit=${limit}`);
