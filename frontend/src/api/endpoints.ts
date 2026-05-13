import { api } from './client';
import type {
  CodeServerStatus,
  EnvironmentCodeServerInstallResponse,
  EnvironmentCreateRequest,
  EnvironmentListResponse,
  EnvironmentRecord,
  EnvironmentUpdateRequest,
  FileListResponse,
  FileReadResponse,
  ProjectCreateRequest,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateRequest,
  ProjectListResponse,
  ProjectRecord,
  ProjectUpdateRequest,
  SkillDetail,
  SkillImportRequest,
  SkillImportResponse,
  SkillListResponse,
  SkillPreview,
  SkillRegistryInstallResponse,
  SkillRegistryListResponse,
  SkillRegistryStatus,
  SkillRegistryUpdateRequest,
  SkillRegistryUpdateResponse,
  SystemHealth,
  TaskCreateRequest,
  TaskListResponse,
  TaskOutputListResponse,
  TaskRecord,
  TaskSummary,
  TerminalSession,
  UserSessionPairListResponse,
  WorkspaceCreateRequest,
  WorkspaceListResponse,
  WorkspaceRecord,
  WorkspaceUpdateRequest,
  ResourcesResponse,
  TaskEdge,
  TaskEdgeCreateRequest,
  TaskEdgeListResponse,
  TaskMessagesResponse,
} from '../types';
import {
  mockArchiveTask,
  mockCancelTask,
  mockDeleteTask,
  mockCreateCodeServerSession,
  mockCreateEnvironment,
  mockCreateProject,
  mockCreateProjectEnvironmentReference,
  mockCreateTask,
  mockCreateTerminalSession,
  mockCreateWorkspace,
  mockDeleteCodeServerSession,
  mockDeleteEnvironment,
  mockDeleteProject,
  mockDeleteProjectEnvironmentReference,
  mockDeleteTerminalSession,
  mockDeleteWorkspace,
  mockDetectEnvironment,
  mockGetCodeServerStatus,
  mockGetEnvironment,
  mockGetEnvironments,
  mockGetHealth,
  mockGetProject,
  mockGetProjectEnvironmentReferences,
  mockGetProjects,
  mockGetTask,
  mockGetTaskOutput,
  mockGetTasks,
  mockGetTerminalSession,
  mockGetWorkspaces,
  mockGetWorkspace,
  mockResetTerminalSession,
  mockGetSessionPairs,
  mockGetSkillDetail,
  mockGetSkills,
  mockImportSkill,
  mockInstallEnvironmentCodeServer,
  mockPreviewSkillSettings,
  mockListFiles,
  mockReadFile,
  mockUpdateEnvironment,
  mockUpdateProject,
  mockUpdateProjectEnvironmentReference,
  mockUpdateWorkspace,
  mockGetResources,
  mockGetProjectTasks,
  mockGetTaskEdges,
  mockCreateTaskEdge,
  mockDeleteTaskEdge,
} from './mock';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
const DEFAULT_PROJECT_ID = 'default';
const API_BASE = '/api';
const API_KEY = import.meta.env.VITE_AINRF_API_KEY?.trim() ?? '';

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

export const getSkills = (): Promise<SkillListResponse> =>
  USE_MOCK ? Promise.resolve(mockGetSkills()) : api.get<SkillListResponse>('/skills');

export const getSkillDetail = (skillId: string): Promise<SkillDetail> =>
  USE_MOCK
    ? Promise.resolve(mockGetSkillDetail(skillId))
    : api.get<SkillDetail>(`/skills/${skillId}`);

export const previewSkillSettings = (skillId: string): Promise<SkillPreview> =>
  USE_MOCK
    ? Promise.resolve(mockPreviewSkillSettings(skillId))
    : api.get<SkillPreview>(`/skills/${skillId}/preview`);

export const importSkill = (payload: SkillImportRequest): Promise<SkillImportResponse> =>
  USE_MOCK
    ? Promise.resolve(mockImportSkill(payload))
    : api.post<SkillImportResponse>('/skills/import', payload);

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

export const getWorkspaces = (): Promise<WorkspaceListResponse> =>
  USE_MOCK ? Promise.resolve(mockGetWorkspaces()) : api.get<WorkspaceListResponse>('/workspaces');

export const getWorkspace = (workspaceId: string): Promise<WorkspaceRecord> =>
  USE_MOCK
    ? Promise.resolve(mockGetWorkspace(workspaceId))
    : api.get<WorkspaceRecord>(`/workspaces/${workspaceId}`);

export const createWorkspace = (payload: WorkspaceCreateRequest): Promise<WorkspaceRecord> =>
  USE_MOCK
    ? Promise.resolve(mockCreateWorkspace(payload))
    : api.post<WorkspaceRecord>('/workspaces', payload);

export const updateWorkspace = (
  workspaceId: string,
  payload: WorkspaceUpdateRequest
): Promise<WorkspaceRecord> =>
  USE_MOCK
    ? Promise.resolve(mockUpdateWorkspace(workspaceId, payload))
    : api.patch<WorkspaceRecord>(`/workspaces/${workspaceId}`, payload);

export const deleteWorkspace = (workspaceId: string): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteWorkspace(workspaceId))
    : api.delete<void>(`/workspaces/${workspaceId}`);

export const getTasks = (includeArchived: boolean = false): Promise<TaskListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTasks())
    : api.get<TaskListResponse>(`/tasks?include_archived=${includeArchived}`);

export const getTask = (taskId: string): Promise<TaskRecord> =>
  USE_MOCK ? Promise.resolve(mockGetTask(taskId)) : api.get<TaskRecord>(`/tasks/${taskId}`);

export const createTask = (payload: TaskCreateRequest): Promise<TaskSummary> =>
  USE_MOCK ? Promise.resolve(mockCreateTask(payload)) : api.post<TaskSummary>('/tasks', payload);

export const archiveTask = (taskId: string): Promise<TaskSummary> =>
  USE_MOCK ? Promise.resolve(mockArchiveTask(taskId)) : api.delete<TaskSummary>(`/tasks/${taskId}`);

export const deleteTask = (taskId: string): Promise<void> =>
  USE_MOCK ? mockDeleteTask(taskId) : api.delete<void>(`/tasks/${taskId}/permanent`);

export const cancelTask = (taskId: string): Promise<TaskSummary> =>
  USE_MOCK ? Promise.resolve(mockCancelTask(taskId)) : api.post<TaskSummary>(`/tasks/${taskId}/cancel`, {});

export const getProjectTasks = (projectId: string, includeArchived: boolean = false): Promise<TaskListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetProjectTasks())
    : api.get<TaskListResponse>(`/projects/${projectId}/tasks?include_archived=${includeArchived}`);

export const getTaskEdges = (projectId: string): Promise<TaskEdgeListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTaskEdges(projectId))
    : api.get<TaskEdgeListResponse>(`/projects/${projectId}/task-edges`);

export const createTaskEdge = (
  projectId: string,
  payload: TaskEdgeCreateRequest
): Promise<TaskEdge> =>
  USE_MOCK
    ? Promise.resolve(mockCreateTaskEdge(projectId, payload))
    : api.post<TaskEdge>(`/projects/${projectId}/task-edges`, payload);

export const deleteTaskEdge = (edgeId: string): Promise<void> =>
  USE_MOCK
    ? Promise.resolve(mockDeleteTaskEdge(edgeId))
    : api.delete<void>(`/task-edges/${edgeId}`);

export const getTaskOutput = (
  taskId: string,
  afterSeq: number = 0
): Promise<TaskOutputListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockGetTaskOutput(taskId, afterSeq))
    : api.get<TaskOutputListResponse>(`/tasks/${taskId}/output?after_seq=${afterSeq}`);

export const buildTaskStreamUrl = (taskId: string, afterSeq: number = 0): string => {
  const search = new URLSearchParams({ after_seq: String(afterSeq) });
  if (API_KEY) {
    // Native EventSource cannot attach arbitrary headers, so stream auth stays in the URL.
    search.set('api_key', API_KEY);
  }
  return `${API_BASE}/tasks/${taskId}/stream?${search.toString()}`;
};

export const pauseTask = (taskId: string): Promise<TaskSummary> =>
  api.post<TaskSummary>(`/tasks/${taskId}/pause`, {});

export const resumeTask = (taskId: string): Promise<TaskSummary> =>
  api.post<TaskSummary>(`/tasks/${taskId}/resume`, {});

export const sendTaskPrompt = (taskId: string, prompt: string): Promise<{ task_id: string; sequence: number }> =>
  api.post<{ task_id: string; sequence: number }>(`/tasks/${taskId}/prompt`, { prompt });

export const getTaskMessages = (taskId: string, afterSeq: number = 0, limit: number = 100): Promise<TaskMessagesResponse> =>
  api.get<TaskMessagesResponse>(`/tasks/${taskId}/messages?after_seq=${afterSeq}&limit=${limit}`);

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

export const installEnvironmentCodeServer = (
  environmentId: string
): Promise<EnvironmentCodeServerInstallResponse> =>
  USE_MOCK
    ? Promise.resolve(mockInstallEnvironmentCodeServer(environmentId))
    : api.post<EnvironmentCodeServerInstallResponse>(
        `/environments/${environmentId}/install-code-server`,
        {}
      );

export const getProjects = (): Promise<ProjectListResponse> =>
  USE_MOCK ? Promise.resolve(mockGetProjects()) : api.get<ProjectListResponse>('/projects');

export const getProject = (projectId: string): Promise<ProjectRecord> =>
  USE_MOCK ? Promise.resolve(mockGetProject(projectId)) : api.get<ProjectRecord>(`/projects/${projectId}`);

export const createProject = (payload: ProjectCreateRequest): Promise<ProjectRecord> =>
  USE_MOCK ? Promise.resolve(mockCreateProject(payload)) : api.post<ProjectRecord>('/projects', payload);

export const updateProject = (projectId: string, payload: ProjectUpdateRequest): Promise<ProjectRecord> =>
  USE_MOCK
    ? Promise.resolve(mockUpdateProject(projectId, payload))
    : api.patch<ProjectRecord>(`/projects/${projectId}`, payload);

export const deleteProject = (projectId: string): Promise<void> =>
  USE_MOCK ? Promise.resolve(mockDeleteProject(projectId)) : api.delete<void>(`/projects/${projectId}`);

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

export const listFiles = (
  environmentId: string,
  path: string = '',
  workspaceId?: string
): Promise<FileListResponse> =>
  USE_MOCK
    ? Promise.resolve(mockListFiles(environmentId, path))
    : api.get<FileListResponse>(
        `/files/list?environment_id=${encodeURIComponent(environmentId)}&path=${encodeURIComponent(path)}${
          workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''
        }`
      );

export const readFile = (
  environmentId: string,
  path: string,
  workspaceId?: string
): Promise<FileReadResponse> =>
  USE_MOCK
    ? Promise.resolve(mockReadFile(environmentId, path))
    : api.get<FileReadResponse>(
        `/files/read?environment_id=${encodeURIComponent(environmentId)}&path=${encodeURIComponent(path)}${
          workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''
        }`
      );

export const buildFileStreamUrl = (
  environmentId: string,
  path: string,
  workspaceId?: string
): string =>
  `/api/files/stream?environment_id=${encodeURIComponent(environmentId)}&path=${encodeURIComponent(path)}${
    workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ''
  }`;

export const getResources = (): Promise<ResourcesResponse> =>
  USE_MOCK ? Promise.resolve(mockGetResources()) : api.get<ResourcesResponse>('/resources');

// --- Skill Registry API ---

export const getSkillRegistries = (): Promise<SkillRegistryListResponse> =>
  USE_MOCK
    ? Promise.resolve({ items: [] })
    : api.get<SkillRegistryListResponse>('/skill-registries');

export const getSkillRegistryStatus = (registryId: string): Promise<SkillRegistryStatus> =>
  USE_MOCK
    ? Promise.resolve({
        registry_id: registryId,
        installed: false,
        installed_count: 0,
        last_sync_at: null,
        remote_commit: null,
        local_commit: null,
        has_update: false,
        is_dirty: false,
        sync_in_progress: false,
      })
    : api.get<SkillRegistryStatus>(`/skill-registries/${registryId}/status`);

export const installSkillRegistry = (registryId: string): Promise<SkillRegistryInstallResponse> =>
  USE_MOCK
    ? Promise.resolve({ registry_id: registryId, installed_count: 0, skills: [] })
    : api.post<SkillRegistryInstallResponse>(`/skill-registries/${registryId}/install`, {});

export const updateSkillRegistry = (
  registryId: string,
  payload: SkillRegistryUpdateRequest
): Promise<SkillRegistryUpdateResponse> =>
  USE_MOCK
    ? Promise.resolve({ registry_id: registryId, updated_count: 0, added: [], removed: [] })
    : api.post<SkillRegistryUpdateResponse>(`/skill-registries/${registryId}/update`, payload);
