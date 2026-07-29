import { api } from '@/shared/api/client';
import type {
  TaskEdge,
  TaskEdgeListResponse,
  TaskListResponse,
  TaskMessagesResponse,
  TaskOutputListResponse,
  TaskRecord,
  TaskRetryResponse,
  TaskSummary,
  TaskTokenUsageSummary,
} from '@/shared/types';
import type {
  TaskCreatePayload,
  TaskEdgeCreateRequest,
  TaskUpdateProjectRequest,
} from '@/shared/api/transportTypes';

const API_BASE = '/api';
const API_KEY = import.meta.env.VITE_OPENSCIENCE_API_KEY?.trim()
  || import.meta.env.VITE_AINRF_API_KEY?.trim()
  || '';

export const getTasks = (params: {
  includeArchived?: boolean;
  cursor?: string;
  limit?: number;
  sort?: 'updated' | 'created' | 'name';
} = {}): Promise<TaskListResponse> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? false) });
  if (params.cursor) search.set('cursor', params.cursor);
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

export const createTask = (payload: TaskCreatePayload, idempotencyKey: string): Promise<TaskSummary> =>
  api.post('/tasks', payload, { headers: { 'Idempotency-Key': idempotencyKey } });

function taskAction(taskId: string, action: string, idempotencyKey: string): Promise<TaskSummary> {
  return api.post(`/tasks/${taskId}/${action}`, {}, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
}

export const archiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'archive', key);
export const unarchiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'unarchive', key);
export const cancelTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'cancel', key);
export const pauseTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'pause', key);
export const resumeTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskAction(taskId, 'resume', key);

export const deleteTask = (taskId: string): Promise<void> => api.delete(`/tasks/${taskId}/permanent`);
export const retryTask = (taskId: string, key: string): Promise<TaskRetryResponse> =>
  api.post(`/tasks/${taskId}/retry`, {}, { headers: { 'Idempotency-Key': key } });

export const moveTask = (
  taskId: string,
  payload: { project_id: string; context_version_id: string },
  key: string,
): Promise<TaskSummary> => api.post(`/tasks/${taskId}/move`, payload, {
  headers: { 'Idempotency-Key': key },
});

export const forkTask = (
  taskId: string,
  payload: { workspace_id: string; project_id?: string; prompt?: string; title?: string },
  key: string,
): Promise<TaskSummary> => api.post(`/tasks/${taskId}/fork`, payload, {
  headers: { 'Idempotency-Key': key },
});

export const updateTaskProject = (taskId: string, projectId: string): Promise<TaskSummary> =>
  api.patch(`/tasks/${taskId}/project`, {
    project_id: projectId,
  } satisfies TaskUpdateProjectRequest);

export const updateTask = (
  taskId: string,
  data: { title?: string },
  key: string,
): Promise<TaskSummary> => api.patch(`/tasks/${taskId}`, data, {
  headers: { 'Idempotency-Key': key },
});

export const getProjectTasks = (
  projectId: string,
  params: { includeArchived?: boolean; cursor?: string; limit?: number } = {},
): Promise<TaskListResponse> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? false) });
  if (params.cursor) search.set('cursor', params.cursor);
  if (params.limit) search.set('limit', String(params.limit));
  return api.get(`/projects/${projectId}/tasks?${search.toString()}`);
};

export const getTaskEdges = (projectId: string): Promise<TaskEdgeListResponse> =>
  api.get(`/projects/${projectId}/task-edges`);
export const createTaskEdge = (
  projectId: string,
  payload: TaskEdgeCreateRequest,
  key: string,
): Promise<TaskEdge> => api.post(`/projects/${projectId}/task-edges`, payload, {
  headers: { 'Idempotency-Key': key },
});
export const deleteTaskEdge = (edgeId: string): Promise<void> => api.delete(`/task-edges/${edgeId}`);

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
