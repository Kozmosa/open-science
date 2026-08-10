import { api } from '@/shared/api/client';
import {
  adaptTask,
  adaptTaskList,
  adaptTaskTurn,
  adaptTaskTurnItem,
  adaptForkPreview,
  toTaskCreateRequest,
} from '../types';
import type {
  TaskEdge,
  TaskEdgeListResponse,
  TaskListResponse,
  TaskCreateInput,
  ForkPreview,
  TaskSummary,
  TaskTurnItem,
  TaskTurnItemListResponse,
  TaskTurnListResponse,
} from '../types';
import type {
  ConversationTaskMutationResponse,
  ForkConfirmRequest,
  ForkConfirmResponse,
  ForkPreviewRequest,
  ForkPreviewResponse,
  TaskCreateRequest,
  TaskListResponse as TransportTaskListResponse,
  TaskMoveRequest,
  TaskRelationshipCreateRequest,
  TaskRelationshipListResponse,
  TaskRelationshipResponse,
  TaskSummaryResponse,
  TaskUpdateRequest,
  TurnControlResponse,
  TurnItemListResponse as TransportTurnItemListResponse,
  TurnListResponse as TransportTurnListResponse,
  TurnSubmissionResponse,
} from '@/generated/transport';

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
  return api.get<TransportTaskListResponse>(`/tasks?${search.toString()}`).then(adaptTaskList);
};

export const getTask = (taskId: string): Promise<TaskSummary> =>
  api.get<TaskSummaryResponse>(`/tasks/${taskId}`).then(adaptTask);

export const createTask = async (
  payload: TaskCreateInput,
  idempotencyKey: string,
): Promise<TaskSummary> => {
  const request: TaskCreateRequest = toTaskCreateRequest(payload);
  const response = await api.post<ConversationTaskMutationResponse>('/tasks', request, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });
  return adaptTask(response.task);
};

function taskLifecycleAction(
  taskId: string,
  action: 'archive' | 'unarchive' | 'complete' | 'reopen',
  idempotencyKey: string,
): Promise<TaskSummary> {
  return api.post<TaskSummaryResponse>(`/tasks/${taskId}/${action}`, {}, {
    headers: { 'Idempotency-Key': idempotencyKey },
  }).then(adaptTask);
}

export const archiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskLifecycleAction(taskId, 'archive', key);
export const unarchiveTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskLifecycleAction(taskId, 'unarchive', key);
export const completeTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskLifecycleAction(taskId, 'complete', key);
export const reopenTask = (taskId: string, key: string): Promise<TaskSummary> =>
  taskLifecycleAction(taskId, 'reopen', key);
export const cancelTask = (taskId: string, key: string): Promise<void> =>
  api.post(`/tasks/${taskId}/cancel`, {}, { headers: { 'Idempotency-Key': key } });
export const getTaskTurns = (taskId: string): Promise<TaskTurnListResponse> =>
  api.get<TransportTurnListResponse>(`/tasks/${taskId}/turns`).then((response) => ({
    items: response.items.map(adaptTaskTurn),
  }));

export const getTurnItems = (taskId: string, turnId: string): Promise<TaskTurnItemListResponse> =>
  api.get<TransportTurnItemListResponse>(`/tasks/${taskId}/turns/${turnId}/items`).then((response) => ({
    items: response.items.map(adaptTaskTurnItem),
  }));

export const createTurn = (
  taskId: string,
  text: string,
  key: string,
  allowNextTurn = false,
): Promise<TurnSubmissionResponse> => api.post<TurnSubmissionResponse>(
  `/tasks/${taskId}/turns`,
  { text, allow_next_turn: allowNextTurn },
  { headers: { 'Idempotency-Key': key } },
);

export const steerTurn = (
  taskId: string,
  turnId: string,
  text: string,
  key: string,
): Promise<TurnControlResponse> => api.post<TurnControlResponse>(
  `/tasks/${taskId}/turns/${turnId}/steer`,
  { expected_turn_id: turnId, text },
  { headers: { 'Idempotency-Key': key } },
);

export const interruptTurn = (
  taskId: string,
  turnId: string,
  key: string,
): Promise<TurnControlResponse> => api.post<TurnControlResponse>(
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
  return api.post<TurnSubmissionResponse>(
    `/tasks/${taskId}/turns/${terminal.turn_id}/retry`,
    { text, allow_next_turn: false },
    { headers: { 'Idempotency-Key': key } },
  );
};

export const moveTask = (
  taskId: string,
  payload: TaskMoveRequest,
  key: string,
): Promise<TaskSummary> => api.post<TaskSummaryResponse>(`/tasks/${taskId}/move`, payload, {
  headers: { 'Idempotency-Key': key },
}).then(adaptTask);

export const previewFork = (
  taskId: string,
  payload: ForkPreviewRequest,
  key: string,
): Promise<ForkPreview> => api.post<ForkPreviewResponse>(`/tasks/${taskId}/fork-preview`, payload, {
  headers: { 'Idempotency-Key': key },
}).then(adaptForkPreview);

export const confirmFork = async (
  taskId: string,
  previewId: string,
  payload: ForkConfirmRequest,
  key: string,
): Promise<TaskSummary> => {
  const response = await api.post<ForkConfirmResponse>(
    `/tasks/${taskId}/fork-preview/${previewId}/confirm`,
    payload,
    {
      headers: { 'Idempotency-Key': key },
    },
  );
  return getTask(response.target_task_id);
};

export const updateTask = (
  taskId: string,
  data: TaskUpdateRequest,
  key: string,
): Promise<TaskSummary> => api.patch<TaskSummaryResponse>(`/tasks/${taskId}`, data, {
  headers: { 'Idempotency-Key': key },
}).then(adaptTask);

export const getProjectTasks = (
  projectId: string,
  params: { includeArchived?: boolean; limit?: number } = {},
): Promise<TaskListResponse> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? false) });
  search.set('project_id', projectId);
  if (params.limit) search.set('limit', String(params.limit));
  return api.get<TransportTaskListResponse>(`/tasks?${search.toString()}`).then(adaptTaskList);
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

export const listCanonicalTaskItems = async (taskId: string): Promise<TaskTurnItem[]> => {
  const turns = await getTaskTurns(taskId);
  const pages = await Promise.all(turns.items.map((turn) => getTurnItems(taskId, turn.turn_id)));
  return pages.flatMap((page) => page.items).sort((a, b) => a.task_item_seq - b.task_item_seq);
};
