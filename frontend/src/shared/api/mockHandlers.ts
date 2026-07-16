import { http, HttpResponse } from 'msw';
import type {
  EnvironmentCreateRequest,
  EnvironmentUpdateRequest,
  LiteratureTopicInput,
  ProjectCreateRequest,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceUpdateRequest,
  ProjectUpdateRequest,
  SessionCreateRequest,
  SessionUpdateRequest,
  SkillImportRequest,
  TaskCreatePayload,
  TaskEdgeCreateRequest,
  WorkspaceCreateRequest,
  WorkspaceUpdateRequest,
} from '@/shared/types';
import { ApiError } from './client';
import {
  mockArchiveTask,
  mockCancelTask,
  mockCreateEnvironment,
  mockCreateProject,
  mockCreateProjectEnvironmentReference,
  mockCreateSession,
  mockCreateTask,
  mockCreateTaskEdge,
  mockCreateTerminalSession,
  mockCreateWorkspace,
  mockDeleteEnvironment,
  mockDeleteProject,
  mockDeleteProjectEnvironmentReference,
  mockDeleteSession,
  mockDeleteTask,
  mockDeleteTaskEdge,
  mockDeleteTerminalSession,
  mockDeleteWorkspace,
  mockDetectEnvironment,
  mockGetAttempts,
  mockGetEnvironment,
  mockGetEnvironments,
  mockGetHealth,
  mockGetProject,
  mockGetProjectEnvironmentReferences,
  mockGetProjects,
  mockGetProjectTasks,
  mockGetResources,
  mockGetSession,
  mockGetSessionPairs,
  mockGetSessions,
  mockGetSkillDetail,
  mockGetSkills,
  mockGetTask,
  mockGetTaskEdges,
  mockGetTaskOutput,
  mockGetTasks,
  mockGetTerminalSession,
  mockGetWorkspace,
  mockGetWorkspaces,
  mockImportSkill,
  mockListFiles,
  mockPreviewSkillSettings,
  mockReadFile,
  mockResetTerminalSession,
  mockUpdateEnvironment,
  mockUpdateProject,
  mockUpdateProjectEnvironmentReference,
  mockUpdateSession,
  mockUpdateTaskProject,
  mockUpdateWorkspace,
  resetMockEnvironmentState,
  resetMockTaskState,
  resetMockTerminalSession,
} from './mock';

type Params = Record<string, string | readonly string[] | undefined>;

function textParam(params: Params, name: string): string {
  const value = params[name];
  if (typeof value !== 'string') {
    throw new Error(`Missing mock route parameter: ${name}`);
  }
  return value;
}

function mockJson<T>(factory: () => T): Response {
  try {
    return HttpResponse.json(factory() as never);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 400;
    const detail = error instanceof Error ? error.message : 'Mock request failed';
    return HttpResponse.json({ detail }, { status });
  }
}

function mockEmpty(factory: () => void | Promise<void>): Response | Promise<Response> {
  try {
    const result = factory();
    if (result instanceof Promise) {
      return result
        .then(() => new HttpResponse(null, { status: 204 }))
        .catch((error: unknown) => {
          const status = error instanceof ApiError ? error.status : 400;
          const detail = error instanceof Error ? error.message : 'Mock request failed';
          return HttpResponse.json({ detail }, { status });
        });
    }
    return new HttpResponse(null, { status: 204 });
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 400;
    const detail = error instanceof Error ? error.message : 'Mock request failed';
    return HttpResponse.json({ detail }, { status });
  }
}

const taskUsage = {
  task_count: 0,
  tasks_with_usage: 0,
  total_tokens: 0,
  total_cost_usd: 0,
  total_duration_ms: 0,
  median_duration_ms: null,
  total: {
    input_tokens: 0,
    output_tokens: 0,
    cache_creation_input_tokens: 0,
    cache_read_input_tokens: 0,
    cost_usd: 0,
  },
  by_model: {},
  by_engine: {},
  top_tasks: [],
};

const mockUser = {
  id: 'mock-browser-user',
  username: 'mock-owner',
  display_name: 'Mock Owner',
  role: 'member',
  status: 'active',
  must_change_password: false,
};

function resolveJson<Resolver>(resolver: Resolver): Resolver {
  return resolver;
}

export const legacyMockHandlers = [
  http.get('/build-info.json', () => HttpResponse.json({ short_commit: null, committed_at: null })),
  http.get('/api/health', () => HttpResponse.json(mockGetHealth())),
  http.get('/api/settings/codex-defaults', () => HttpResponse.json({ codex_config_toml: null, codex_auth_json: null })),
  http.get('/api/settings/deployment-version', () => HttpResponse.json({ short_commit: null, committed_at: null })),
  http.get('/api/settings/monitoring', () => HttpResponse.json({
    services: [
      { id: 'grafana', display_name: 'Grafana', description: 'Metrics dashboards, alerts, and visualization', url: '/grafana', icon: 'grafana' },
      { id: 'prometheus', display_name: 'Prometheus', description: 'Time-series metrics collection and querying', url: '/prometheus', icon: 'prometheus' },
      { id: 'litefuse', display_name: 'Litefuse', description: 'LLM observability: traces, generations, and token analytics', url: '/litefuse/', icon: 'litefuse' },
    ],
  })),

  http.post('/api/auth/login', () => HttpResponse.json({ access_token: 'mock-access-token', refresh_token: 'mock-refresh-token', user: mockUser })),
  http.post('/api/auth/register', () => HttpResponse.json({ message: 'Mock account is ready.' }, { status: 201 })),
  http.post('/api/auth/refresh', () => HttpResponse.json({ access_token: 'mock-access-token' })),
  http.post('/api/auth/logout', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/auth/change-password', () => new HttpResponse(null, { status: 204 })),
  http.get('/api/auth/me', () => HttpResponse.json(mockUser)),

  http.get('/api/skills', () => HttpResponse.json(mockGetSkills())),
  http.get('/api/skills/:skillId', ({ params }) => mockJson(() => mockGetSkillDetail(textParam(params, 'skillId')))),
  http.get('/api/skills/:skillId/preview', ({ params }) => mockJson(() => mockPreviewSkillSettings(textParam(params, 'skillId')))),
  http.post('/api/skills/import', resolveJson(async ({ request }) => {
    const body = await request.json() as SkillImportRequest;
    return mockJson(() => mockImportSkill(body));
  })),

  http.get('/api/terminal/session', ({ request }) => HttpResponse.json(mockGetTerminalSession(new URL(request.url).searchParams.get('environment_id') ?? undefined))),
  http.get('/api/terminal/session-pairs', ({ request }) => HttpResponse.json(mockGetSessionPairs(new URL(request.url).searchParams.get('environment_id') ?? undefined))),
  http.post('/api/terminal/session', resolveJson(async ({ request }) => {
    const body = await request.json() as { environment_id: string };
    return mockJson(() => mockCreateTerminalSession(body.environment_id));
  })),
  http.delete('/api/terminal/session', ({ request }) => {
    const search = new URL(request.url).searchParams;
    return mockJson(() => mockDeleteTerminalSession(search.get('environment_id'), search.get('attachment_id')));
  }),
  http.post('/api/terminal/session/reset', resolveJson(async ({ request }) => {
    const body = await request.json() as { environment_id: string };
    return mockJson(() => mockResetTerminalSession(body.environment_id));
  })),

  http.get('/api/workspaces', () => HttpResponse.json(mockGetWorkspaces())),
  http.get('/api/workspaces/:workspaceId', ({ params }) => mockJson(() => mockGetWorkspace(textParam(params, 'workspaceId')))),
  http.post('/api/workspaces', resolveJson(async ({ request }) => {
    const body = await request.json() as WorkspaceCreateRequest;
    return mockJson(() => mockCreateWorkspace(body));
  })),
  http.patch('/api/workspaces/:workspaceId', resolveJson(async ({ params, request }) => {
    const body = await request.json() as WorkspaceUpdateRequest;
    return mockJson(() => mockUpdateWorkspace(textParam(params, 'workspaceId'), body));
  })),
  http.delete('/api/workspaces/:workspaceId', ({ params }) => mockEmpty(() => mockDeleteWorkspace(textParam(params, 'workspaceId')))),

  http.get('/api/tasks', () => HttpResponse.json(mockGetTasks())),
  http.get('/api/tasks/token-usage', () => HttpResponse.json(taskUsage)),
  http.get('/api/tasks/:taskId', ({ params }) => mockJson(() => mockGetTask(textParam(params, 'taskId')))),
  http.post('/api/tasks', resolveJson(async ({ request }) => {
    const body = await request.json() as TaskCreatePayload;
    return mockJson(() => mockCreateTask(body));
  })),
  http.post('/api/tasks/:taskId/archive', ({ params }) => mockJson(() => mockArchiveTask(textParam(params, 'taskId')))),
  http.post('/api/tasks/:taskId/cancel', ({ params }) => mockJson(() => mockCancelTask(textParam(params, 'taskId')))),
  http.patch('/api/tasks/:taskId/project', resolveJson(async ({ params, request }) => {
    const body = await request.json() as { project_id: string };
    return mockJson(() => mockUpdateTaskProject(textParam(params, 'taskId'), body.project_id));
  })),
  http.delete('/api/tasks/:taskId/permanent', ({ params }) => mockEmpty(() => mockDeleteTask(textParam(params, 'taskId')))),
  http.get('/api/tasks/:taskId/output', ({ params, request }) => {
    const afterSeq = Number(new URL(request.url).searchParams.get('after_seq') ?? 0);
    return mockJson(() => mockGetTaskOutput(textParam(params, 'taskId'), afterSeq));
  }),

  http.get('/api/environments', () => HttpResponse.json(mockGetEnvironments())),
  http.get('/api/environments/:environmentId', ({ params }) => mockJson(() => mockGetEnvironment(textParam(params, 'environmentId')))),
  http.post('/api/environments', resolveJson(async ({ request }) => {
    const body = await request.json() as EnvironmentCreateRequest;
    return mockJson(() => mockCreateEnvironment(body));
  })),
  http.patch('/api/environments/:environmentId', resolveJson(async ({ params, request }) => {
    const body = await request.json() as EnvironmentUpdateRequest;
    return mockJson(() => mockUpdateEnvironment(textParam(params, 'environmentId'), body));
  })),
  http.delete('/api/environments/:environmentId', ({ params }) => mockEmpty(() => mockDeleteEnvironment(textParam(params, 'environmentId')))),
  http.post('/api/environments/:environmentId/detect', ({ params }) => mockJson(() => mockDetectEnvironment(textParam(params, 'environmentId')))),

  http.get('/api/projects', () => HttpResponse.json(mockGetProjects())),
  http.get('/api/projects/:projectId', ({ params }) => mockJson(() => mockGetProject(textParam(params, 'projectId')))),
  http.post('/api/projects', resolveJson(async ({ request }) => {
    const body = await request.json() as ProjectCreateRequest;
    return mockJson(() => mockCreateProject(body));
  })),
  http.patch('/api/projects/:projectId', resolveJson(async ({ params, request }) => {
    const body = await request.json() as ProjectUpdateRequest;
    return mockJson(() => mockUpdateProject(textParam(params, 'projectId'), body));
  })),
  http.delete('/api/projects/:projectId', ({ params }) => mockEmpty(() => mockDeleteProject(textParam(params, 'projectId')))),
  http.get('/api/projects/:projectId/tasks', () => HttpResponse.json(mockGetProjectTasks())),
  http.get('/api/projects/:projectId/task-edges', ({ params }) => HttpResponse.json(mockGetTaskEdges(textParam(params, 'projectId')))),
  http.post('/api/projects/:projectId/task-edges', resolveJson(async ({ params, request }) => {
    const body = await request.json() as TaskEdgeCreateRequest;
    return mockJson(() => mockCreateTaskEdge(textParam(params, 'projectId'), body));
  })),
  http.delete('/api/task-edges/:edgeId', ({ params }) => mockEmpty(() => mockDeleteTaskEdge(textParam(params, 'edgeId')))),
  http.get('/api/projects/:projectId/environment-refs', ({ params }) => HttpResponse.json(mockGetProjectEnvironmentReferences(textParam(params, 'projectId')))),
  http.post('/api/projects/:projectId/environment-refs', resolveJson(async ({ params, request }) => {
    const body = await request.json() as ProjectEnvironmentReferenceCreateRequest;
    return mockJson(() => mockCreateProjectEnvironmentReference(textParam(params, 'projectId'), body));
  })),
  http.patch('/api/projects/:projectId/environment-refs/:environmentId', resolveJson(async ({ params, request }) => {
    const body = await request.json() as ProjectEnvironmentReferenceUpdateRequest;
    return mockJson(() => mockUpdateProjectEnvironmentReference(textParam(params, 'projectId'), textParam(params, 'environmentId'), body));
  })),
  http.delete('/api/projects/:projectId/environment-refs/:environmentId', ({ params }) => mockEmpty(() => mockDeleteProjectEnvironmentReference(textParam(params, 'projectId'), textParam(params, 'environmentId')))),
  http.get('/api/projects/:projectId/cost-summary', ({ params }) => HttpResponse.json({ project_id: textParam(params, 'projectId'), total_cost_usd: 0, total_tokens: 0, session_count: 0, by_model: {} })),

  http.get('/api/files/list', ({ request }) => {
    const search = new URL(request.url).searchParams;
    return HttpResponse.json(mockListFiles(search.get('environment_id') ?? '', search.get('path') ?? ''));
  }),
  http.get('/api/files/read', ({ request }) => {
    const search = new URL(request.url).searchParams;
    return HttpResponse.json(mockReadFile(search.get('environment_id') ?? '', search.get('path') ?? ''));
  }),
  http.post('/api/files/upload', resolveJson(async ({ request }) => {
    const formData = await request.formData();
    const file = formData.get('file');
    return HttpResponse.json({ path: String(formData.get('path') ?? ''), size: file instanceof File ? file.size : 0 });
  })),
  http.get('/api/resources', () => HttpResponse.json(mockGetResources())),

  http.get('/api/skill-registries', () => HttpResponse.json({ items: [] })),
  http.get('/api/skill-registries/:registryId/status', ({ params }) => HttpResponse.json({ registry_id: textParam(params, 'registryId'), installed: false, installed_count: 0, last_sync_at: null, remote_commit: null, local_commit: null, has_update: false, is_dirty: false, sync_in_progress: false })),
  http.post('/api/skill-registries/:registryId/install', ({ params }) => HttpResponse.json({ registry_id: textParam(params, 'registryId'), installed_count: 0, skills: [] })),
  http.post('/api/skill-registries/:registryId/update', ({ params }) => HttpResponse.json({ registry_id: textParam(params, 'registryId'), updated_count: 0, added: [], removed: [] })),

  http.get('/api/sessions', ({ request }) => {
    const search = new URL(request.url).searchParams;
    return HttpResponse.json(mockGetSessions({ projectId: search.get('project_id') ?? undefined, status: search.get('status') ?? undefined }));
  }),
  http.get('/api/sessions/:sessionId', ({ params }) => mockJson(() => mockGetSession(textParam(params, 'sessionId')))),
  http.post('/api/sessions', resolveJson(async ({ request }) => {
    const body = await request.json() as SessionCreateRequest;
    return mockJson(() => mockCreateSession(body));
  })),
  http.patch('/api/sessions/:sessionId', resolveJson(async ({ params, request }) => {
    const body = await request.json() as SessionUpdateRequest;
    return mockJson(() => mockUpdateSession(textParam(params, 'sessionId'), body));
  })),
  http.delete('/api/sessions/:sessionId', ({ params }) => mockEmpty(() => mockDeleteSession(textParam(params, 'sessionId')))),
  http.get('/api/sessions/:sessionId/attempts', ({ params }) => HttpResponse.json(mockGetAttempts(textParam(params, 'sessionId')))),

  http.get('/api/literature/overview', () => HttpResponse.json({ last_successful_check_at: null, next_scheduled_check_at: null, active_check: null, counts: { today: 0, unread: 0, saved: 0, updated: 0 } })),
  http.get('/api/literature/topics', () => HttpResponse.json({ items: [] })),
  http.post('/api/literature/topics', resolveJson(async ({ request }) => {
    const payload = await request.json() as LiteratureTopicInput;
    return HttpResponse.json({ topic_id: 'mock-topic', user_id: mockUser.id, label: payload.label, include_terms: payload.include_terms, exclude_terms: payload.exclude_terms ?? [], categories: payload.categories, status: 'active', is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), last_matched_at: null });
  })),
  http.post('/api/literature/topics/preview', () => HttpResponse.json({ matched_count: 0, samples: [], local_coverage: { paper_count: 0, complete: false }, needs_check: false })),
  http.patch('/api/literature/topics/:topicId', resolveJson(async ({ params, request }) => HttpResponse.json({ topic_id: textParam(params, 'topicId'), ...(await request.json() as object) }))),
  http.delete('/api/literature/topics/:topicId', () => new HttpResponse(null, { status: 204 })),
  http.get('/api/literature/papers', () => HttpResponse.json({ items: [], next_cursor: null, total: 0 })),
];

export function resetLegacyMockState(): void {
  resetMockTerminalSession();
  resetMockEnvironmentState();
  resetMockTaskState();
}
