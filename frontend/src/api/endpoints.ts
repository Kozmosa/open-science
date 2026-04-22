import { api } from './client';
import type {
  CodeServerStatus,
  EnvironmentCreateRequest,
  EnvironmentListResponse,
  EnvironmentRecord,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateRequest,
  SystemHealth,
  TaskCreateRequest,
  TaskListResponse,
  TaskRecord,
  TaskTerminalBinding,
  TerminalAttachment,
  TerminalSession,
  UserSessionPairListResponse,
} from '../types';
import {
  mockCreateCodeServerSession,
  mockCreateEnvironment,
  mockCreateProjectEnvironmentReference,
  mockCreateTask,
  mockCreateTerminalSession,
  mockCancelTask,
  mockDeleteCodeServerSession,
  mockDeleteEnvironment,
  mockDeleteProjectEnvironmentReference,
  mockDeleteTerminalSession,
  mockDetectEnvironment,
  mockGetCodeServerStatus,
  mockGetEnvironments,
  mockGetSessionPairs,
  mockGetTask,
  mockGetTaskTerminal,
  mockGetTasks,
  mockGetHealth,
  mockGetEnvironment,
  mockGetProjectEnvironmentReferences,
  mockGetTerminalSession,
  mockOpenTaskTerminal,
  mockResetTerminalSession,
  mockUpdateProjectEnvironmentReference,
  mockUpdateEnvironment,
} from './mock';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
const DEFAULT_PROJECT_ID = 'default';

function withEnvironmentId(path: string, environmentId?: string): string {
  if (!environmentId) {
    return path;
  }
  const search = new URLSearchParams({ environment_id: environmentId });
  return `${path}?${search.toString()}`;
}

function withTerminalDetachQuery(
  path: string,
  options: {
    environmentId?: string | null;
    attachmentId?: string | null;
  } = {}
): string {
  const search = new URLSearchParams();
  if (options.environmentId) {
    search.set('environment_id', options.environmentId);
  }
  if (options.attachmentId) {
    search.set('attachment_id', options.attachmentId);
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export const getHealth = (): Promise<SystemHealth> =>
  USE_MOCK ? Promise.resolve(mockGetHealth()) : api.get<SystemHealth>('/health');

export const getTerminalSession = (environmentId?: string): Promise<TerminalSession> =>
  USE_MOCK
    ? Promise.resolve(mockGetTerminalSession(environmentId))
    : api.get<TerminalSession>(withEnvironmentId('/terminal/session', environmentId));

export const getSessionPairs = (environmentId?: string): Promise<UserSessionPairListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetSessionPairs(environmentId))
    : api.get<UserSessionPairListResponse>(withEnvironmentId('/terminal/session-pairs', environmentId));

export const createTerminalSession = (environmentId: string): Promise<TerminalSession> =>
  USE_MOCK
    ? Promise.resolve(mockCreateTerminalSession(environmentId))
    : api.post<TerminalSession>('/terminal/session', { environment_id: environmentId });

export const deleteTerminalSession = (options: {
  environmentId?: string | null;
  attachmentId?: string | null;
}): Promise<TerminalSession> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteTerminalSession(options.environmentId, options.attachmentId))
    : api.delete<TerminalSession>(withTerminalDetachQuery('/terminal/session', options));

export const resetTerminalSession = (
  environmentId: string,
  attachmentId?: string | null
): Promise<TerminalSession> =>
  USE_MOCK
    ? Promise.resolve(mockResetTerminalSession(environmentId))
    : api.post<TerminalSession>('/terminal/session/reset', {
        environment_id: environmentId,
        attachment_id: attachmentId ?? null,
      });

export const getTasks = (environmentId: string): Promise<TaskListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTasks(environmentId))
    : api.get<TaskListResponse>(withEnvironmentId('/tasks', environmentId));

export const getTask = (taskId: string): Promise<TaskRecord> =>
  USE_MOCK ? Promise.resolve(mockGetTask(taskId)) : api.get<TaskRecord>(`/tasks/${taskId}`);

export const createTask = (payload: TaskCreateRequest): Promise<TaskRecord> =>
  USE_MOCK ? Promise.resolve(mockCreateTask(payload)) : api.post<TaskRecord>('/tasks', payload);

export const cancelTask = (taskId: string): Promise<TaskRecord> =>
  USE_MOCK
    ? Promise.resolve(mockCancelTask(taskId))
    : api.post<TaskRecord>(`/tasks/${taskId}/cancel`, {});

export const getTaskTerminal = (taskId: string): Promise<TaskTerminalBinding> =>
  USE_MOCK
    ? Promise.resolve(mockGetTaskTerminal(taskId))
    : api.get<TaskTerminalBinding>(`/tasks/${taskId}/terminal`);

export const openTaskTerminal = (taskId: string): Promise<TerminalAttachment> =>
  USE_MOCK
    ? Promise.resolve(mockOpenTaskTerminal(taskId))
    : api.post<TerminalAttachment>(`/tasks/${taskId}/terminal/open`, {});

export const getCodeServerStatus = (environmentId?: string): Promise<CodeServerStatus> =>
  USE_MOCK
    ? Promise.resolve(mockGetCodeServerStatus(environmentId))
    : api.get<CodeServerStatus>(withEnvironmentId('/code/status', environmentId));

export const createCodeServerSession = (environmentId: string): Promise<CodeServerStatus> =>
  USE_MOCK
    ? Promise.resolve(mockCreateCodeServerSession(environmentId))
    : api.post<CodeServerStatus>('/code/session', { environment_id: environmentId });

export const deleteCodeServerSession = (): Promise<CodeServerStatus> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteCodeServerSession())
    : api.delete<CodeServerStatus>('/code/session');

export const getEnvironments = (): Promise<EnvironmentListResponse> =>
  USE_MOCK ? Promise.resolve(mockGetEnvironments()) : api.get<EnvironmentListResponse>('/environments');

export const getEnvironment = (environmentId: string): Promise<EnvironmentRecord> =>
  USE_MOCK
    ? Promise.resolve(mockGetEnvironment(environmentId))
    : api.get<EnvironmentRecord>(`/environments/${environmentId}`);

export const createEnvironment = (
  payload: EnvironmentCreateRequest
): Promise<EnvironmentRecord> =>
  USE_MOCK
    ? Promise.resolve(mockCreateEnvironment(payload))
    : api.post<EnvironmentRecord>('/environments', payload);

export const updateEnvironment = (
  environmentId: string,
  payload: EnvironmentUpdateRequest
): Promise<EnvironmentRecord> =>
  USE_MOCK
    ? Promise.resolve(mockUpdateEnvironment(environmentId, payload))
    : api.patch<EnvironmentRecord>(`/environments/${environmentId}`, payload);

export const deleteEnvironment = (environmentId: string): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteEnvironment(environmentId))
    : api.delete<void>(`/environments/${environmentId}`);

export const detectEnvironment = (environmentId: string): Promise<EnvironmentRecord> =>
  USE_MOCK
    ? Promise.resolve(mockDetectEnvironment(environmentId))
    : api.post<EnvironmentRecord>(`/environments/${environmentId}/detect`, {});

export const getProjectEnvironmentReferences = (
  projectId: string = DEFAULT_PROJECT_ID
): Promise<ProjectEnvironmentReferenceListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetProjectEnvironmentReferences(projectId))
    : api.get<ProjectEnvironmentReferenceListResponse>(`/projects/${projectId}/environment-refs`);

export const createProjectEnvironmentReference = (
  payload: ProjectEnvironmentReferenceCreateRequest,
  projectId: string = DEFAULT_PROJECT_ID
): Promise<ProjectEnvironmentReference> =>
  USE_MOCK
    ? Promise.resolve(mockCreateProjectEnvironmentReference(projectId, payload))
    : api.post<ProjectEnvironmentReference>(`/projects/${projectId}/environment-refs`, payload);

export const updateProjectEnvironmentReference = (
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest,
  projectId: string = DEFAULT_PROJECT_ID
): Promise<ProjectEnvironmentReference> =>
  USE_MOCK
    ? Promise.resolve(mockUpdateProjectEnvironmentReference(projectId, environmentId, payload))
    : api.patch<ProjectEnvironmentReference>(
        `/projects/${projectId}/environment-refs/${environmentId}`,
        payload
      );

export const deleteProjectEnvironmentReference = (
  environmentId: string,
  projectId: string = DEFAULT_PROJECT_ID
): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteProjectEnvironmentReference(projectId, environmentId))
    : api.delete<void>(`/projects/${projectId}/environment-refs/${environmentId}`);
