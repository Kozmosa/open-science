import { api } from '@/shared/api/client';
import type {
  TaskEdge,
  TaskEdgeListResponse,
  TaskListResponse,
  TaskRecord,
  TaskSummary,
  TaskStatus,
  TaskTokenUsageSummary,
} from '@/shared/types';
import type {
  TaskCreatePayload,
  ConversationTaskMutationResponse,
  TaskMutationResponse,
  TaskRelationshipCreateRequest,
  TaskRelationshipListResponse,
  TaskRelationshipResponse,
  TurnControlResponse,
  TurnItemListResponse,
  TurnItemResponse,
  TurnListResponse,
  TurnSubmissionResponse,
} from '@/shared/api/transportTypes';

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
  const response = await api.post<ConversationTaskMutationResponse>('/tasks', payload, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
  return response.task as unknown as TaskSummary;
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
export const getTaskTurns = (taskId: string): Promise<TurnListResponse> =>
  api.get(`/tasks/${taskId}/turns`);

export const getTurnItems = (taskId: string, turnId: string): Promise<TurnItemListResponse> =>
  api.get(`/tasks/${taskId}/turns/${turnId}/items`);

export const createTurn = (
  taskId: string,
  text: string,
  key: string,
  allowNextTurn = false,
): Promise<TurnSubmissionResponse> => api.post(
  `/tasks/${taskId}/turns`,
  { text, allow_next_turn: allowNextTurn },
  { headers: { 'Idempotency-Key': key } },
);

export const steerTurn = (
  taskId: string,
  turnId: string,
  text: string,
  key: string,
): Promise<TurnControlResponse> => api.post(
  `/tasks/${taskId}/turns/${turnId}/steer`,
  { expected_turn_id: turnId, text },
  { headers: { 'Idempotency-Key': key } },
);

export const interruptTurn = (
  taskId: string,
  turnId: string,
  key: string,
): Promise<TurnControlResponse> => api.post(
  `/tasks/${taskId}/turns/${turnId}/interrupt`,
  { expected_turn_id: turnId },
  { headers: { 'Idempotency-Key': key } },
);

export const retryTask = async (taskId: string, key: string): Promise<TurnSubmissionResponse> => {
  const turns = await getTaskTurns(taskId);
  const terminal = [...turns.items]
    .reverse()
    .find((turn) => ['completed', 'failed', 'interrupted'].includes(turn.status));
  if (!terminal) throw new Error('Task has no terminal Turn to retry');
  const items = await getTurnItems(taskId, terminal.turn_id);
  const userItem = items.items.find((item) => item.item_type === 'user_message');
  const text = userItem?.payload?.text;
  if (typeof text !== 'string' || !text.trim()) {
    throw new Error('Terminal Turn has no retryable user input');
  }
  return api.post(
    `/tasks/${taskId}/turns/${terminal.turn_id}/retry`,
    { text, allow_next_turn: false },
    { headers: { 'Idempotency-Key': key } },
  );
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

export const sendTaskPrompt = async (
  taskId: string,
  prompt: string,
  key: string,
): Promise<TurnSubmissionResponse | TurnControlResponse> => {
  const turns = await getTaskTurns(taskId);
  const active = turns.items.find((turn) => turn.status === 'in_progress');
  return active
    ? await steerTurn(taskId, active.turn_id, prompt, key)
    : await createTurn(taskId, prompt, key);
};

export const listCanonicalTaskItems = async (taskId: string): Promise<TurnItemResponse[]> => {
  const turns = await getTaskTurns(taskId);
  const pages = await Promise.all(turns.items.map((turn) => getTurnItems(taskId, turn.turn_id)));
  return pages.flatMap((page) => page.items).sort((a, b) => a.task_item_seq - b.task_item_seq);
};
