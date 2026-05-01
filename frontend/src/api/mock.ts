import type {
  AnthropicEnvStatus,
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
  SkillItem,
  SkillListResponse,
  SystemHealth,
  TaskCreateRequest,
  TaskListResponse,
  TaskRecord,
  TaskOutputEvent,
  TaskOutputListResponse,
  TaskSummary,
  TerminalSession,
  UserSessionPair,
  UserSessionPairListResponse,
  WorkspaceCreateRequest,
  WorkspaceListResponse,
  WorkspaceRecord,
  WorkspaceUpdateRequest,
} from '../types';

const DEFAULT_PROJECT_ID = 'default';
const MOCK_STATE_ROOT = '.ainrf';
const MOCK_APP_USER_ID = 'mock-browser-user';

const mockHealth: SystemHealth = {
  status: 'ok',
  state_root: MOCK_STATE_ROOT,
  startup_cwd: '/workspace/scholar-agent',
  default_workspace_dir: '/workspace/scholar-agent/workspace/default',
  container_configured: true,
  container_health: {
    ssh_ok: true,
    claude_ok: true,
    project_dir_writable: true,
    claude_version: 'mock',
    gpu_models: ['Mock GPU'],
    cuda_version: 'mock',
    disk_free_bytes: 1024 * 1024 * 1024,
    warnings: [],
  },
  runtime_readiness: {
    ready: false,
    dependencies: {
      tmux: { available: true, path: '/usr/bin/tmux', detail: null },
      uv: { available: true, path: '/usr/bin/uv', detail: null },
      code_server: {
        available: false,
        path: null,
        detail: 'Install code-server from Settings before using the workspace browser.',
      },
    },
  },
  detail: null,
};

let mockEnvironmentCounter = 0;
let mockTerminalAttachmentCounter = 0;
let mockTaskCounter = 0;
let mockWorkspaceCounter = 0;
let mockProjectCounter = 0;
let mockEnvironments: EnvironmentRecord[] = [];
let mockWorkspaces: WorkspaceRecord[] = [];
let mockProjects: ProjectRecord[] = [];
let mockProjectEnvironmentReferences: Record<string, ProjectEnvironmentReference[]> = {
  [DEFAULT_PROJECT_ID]: [],
};
let mockTerminalSessions: Record<string, TerminalSession> = {};
let mockTasks: Record<string, TaskRecord> = {};
let mockTaskOutputs: Record<string, TaskOutputEvent[]> = {};
let mockCodeServerStatus: CodeServerStatus = createUnavailableCodeServerStatus();

function nowIso(): string {
  return new Date().toISOString();
}

function createSeedEnvironment(): EnvironmentRecord {
  const timestamp = nowIso();
  return {
    id: 'env-localhost',
    alias: 'localhost',
    display_name: 'Localhost',
    description: 'Seed SSH profile for the current machine.',
    is_seed: true,
    tags: ['seed', 'default'],
    host: '127.0.0.1',
    port: 22,
    user: 'root',
    auth_kind: 'ssh_key',
    identity_file: null,
    proxy_jump: null,
    proxy_command: null,
    ssh_options: {},
    default_workdir: '/workspace/projects',
    preferred_python: null,
    preferred_env_manager: null,
    preferred_runtime_notes: null,
    task_harness_profile:
      'You are running in the default localhost task harness environment. Prefer repository-local tools.',
    code_server_path: null,
    created_at: timestamp,
    updated_at: timestamp,
    latest_detection: null,
  };
}

function createSeedWorkspace(): WorkspaceRecord {
  const timestamp = nowIso();
  return {
    workspace_id: 'workspace-default',
    project_id: DEFAULT_PROJECT_ID,
    label: 'Repository Default',
    description: 'Seed workspace bound to the current repository checkout.',
    default_workdir: '/workspace/projects',
    workspace_prompt: 'Treat this workspace as the default repository context for the task.',
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function createSeedProject(): ProjectRecord {
  const timestamp = nowIso();
  return {
    project_id: DEFAULT_PROJECT_ID,
    name: 'Default Project',
    description: 'Seed project for the current repository checkout.',
    default_workspace_id: 'workspace-default',
    default_environment_id: 'env-localhost',
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function cloneEnvironment(environment: EnvironmentRecord): EnvironmentRecord {
  return {
    ...environment,
    tags: [...environment.tags],
    ssh_options: { ...environment.ssh_options },
    latest_detection: environment.latest_detection
      ? {
          ...environment.latest_detection,
          errors: [...environment.latest_detection.errors],
          warnings: [...environment.latest_detection.warnings],
          gpu_models: [...environment.latest_detection.gpu_models],
          python: { ...environment.latest_detection.python },
          conda: { ...environment.latest_detection.conda },
          uv: { ...environment.latest_detection.uv },
          pixi: { ...environment.latest_detection.pixi },
          code_server: { ...environment.latest_detection.code_server },
          torch: { ...environment.latest_detection.torch },
          cuda: { ...environment.latest_detection.cuda },
          claude_cli: { ...environment.latest_detection.claude_cli },
        }
      : null,
  };
}

function cloneProjectReference(reference: ProjectEnvironmentReference): ProjectEnvironmentReference {
  return { ...reference };
}

function cloneProject(project: ProjectRecord): ProjectRecord {
  return { ...project };
}

function cloneWorkspace(workspace: WorkspaceRecord): WorkspaceRecord {
  return { ...workspace };
}

function findProject(projectId: string): ProjectRecord {
  const project = mockProjects.find((item) => item.project_id === projectId);
  if (!project) {
    throw new Error(`Project not found: ${projectId}`);
  }
  return project;
}

function findWorkspace(workspaceId: string): WorkspaceRecord {
  const workspace = mockWorkspaces.find((item) => item.workspace_id === workspaceId);
  if (!workspace) {
    throw new Error(`Workspace not found: ${workspaceId}`);
  }
  return workspace;
}

function findEnvironment(environmentId: string): EnvironmentRecord {
  const environment = mockEnvironments.find((item) => item.id === environmentId);
  if (!environment) {
    throw new Error(`Environment not found: ${environmentId}`);
  }
  return environment;
}

function findProjectReference(
  projectId: string,
  environmentId: string
): ProjectEnvironmentReference | null {
  return (
    mockProjectEnvironmentReferences[projectId]?.find(
      (reference) => reference.environment_id === environmentId
    ) ?? null
  );
}

function getProjectReferences(projectId: string): ProjectEnvironmentReference[] {
  return mockProjectEnvironmentReferences[projectId] ?? [];
}

function replaceProjectReference(
  projectId: string,
  reference: ProjectEnvironmentReference
): ProjectEnvironmentReference {
  const current = getProjectReferences(projectId);
  const next = current
    .filter((item) => item.environment_id !== reference.environment_id)
    .map((item) => (reference.is_default ? { ...item, is_default: false } : item));
  next.push(reference);
  mockProjectEnvironmentReferences = {
    ...mockProjectEnvironmentReferences,
    [projectId]: next,
  };
  return reference;
}

function removeProjectReference(projectId: string, environmentId: string): void {
  const current = getProjectReferences(projectId);
  mockProjectEnvironmentReferences = {
    ...mockProjectEnvironmentReferences,
    [projectId]: current.filter((reference) => reference.environment_id !== environmentId),
  };
}

function buildEffectiveWorkdir(environmentId: string, projectId: string = DEFAULT_PROJECT_ID): string {
  const reference = findProjectReference(projectId, environmentId);
  if (reference?.override_workdir) {
    return reference.override_workdir;
  }
  const environment = findEnvironment(environmentId);
  return environment.default_workdir ?? MOCK_STATE_ROOT;
}

function createIdleTerminalSession(
  environmentId: string | null = null,
  environmentAlias: string | null = null,
  workingDirectory: string | null = null
): TerminalSession {
  return {
    session_id: null,
    provider: 'tmux',
    target_kind: environmentId ? 'environment-ssh' : 'daemon-host',
    environment_id: environmentId,
    environment_alias: environmentAlias,
    working_directory: workingDirectory,
    status: 'idle',
    created_at: null,
    started_at: null,
    closed_at: null,
    terminal_ws_url: null,
    detail: null,
    binding_id: null,
    session_name: null,
    attachment_id: null,
    attachment_expires_at: null,
  };
}

function terminalTargetKind(environment: EnvironmentRecord): string {
  return environment.host === '127.0.0.1' || environment.host === 'localhost'
    ? 'environment-local'
    : 'environment-ssh';
}

function shortSessionSuffix(environmentId: string, kind: 'personal' | 'agent'): string {
  const seed = `${MOCK_APP_USER_ID}:${environmentId}:${kind}`;
  let hash = 0;
  for (const character of seed) {
    hash = (hash * 33 + character.charCodeAt(0)) >>> 0;
  }
  return hash.toString(16).padStart(8, '0').slice(0, 8);
}

function terminalSessionName(environmentId: string): string {
  return `p-${shortSessionSuffix(environmentId, 'personal')}`;
}

function createAttachmentUrl(attachmentId: string): string {
  return `ws://127.0.0.1:8000/terminal/attachments/${attachmentId}/ws?token=mock-token-${attachmentId}`;
}

function agentSessionName(environmentId: string): string {
  return `a-${shortSessionSuffix(environmentId, 'agent')}`;
}

function cloneTask(task: TaskRecord): TaskRecord {
  return {
    ...task,
    workspace_summary: { ...task.workspace_summary },
    environment_summary: { ...task.environment_summary },
    binding: task.binding
      ? {
          ...task.binding,
          workspace: { ...task.binding.workspace },
          environment: { ...task.binding.environment },
        }
      : null,
    prompt: task.prompt
      ? {
          ...task.prompt,
          layer_order: [...task.prompt.layer_order],
          layers: task.prompt.layers.map((layer) => ({ ...layer })),
        }
      : null,
    runtime: task.runtime
      ? {
          ...task.runtime,
          command: [...task.runtime.command],
        }
      : null,
    result: { ...task.result },
  };
}

function cloneTaskSummary(task: TaskSummary): TaskSummary {
  return {
    ...task,
    workspace_summary: { ...task.workspace_summary },
    environment_summary: { ...task.environment_summary },
  };
}

function cloneTaskOutput(event: TaskOutputEvent): TaskOutputEvent {
  return { ...event };
}

function deriveTaskTitle(taskInput: string): string {
  const firstLine = taskInput
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return (firstLine ?? 'Untitled task').slice(0, 80);
}

function createMockRunningTerminalSession(
  environment: EnvironmentRecord,
  workingDirectory: string,
  existing?: TerminalSession
): TerminalSession {
  const timestamp = nowIso();
  const attachmentId = `mock-attachment-${environment.id}-${++mockTerminalAttachmentCounter}`;
  return {
    session_id: terminalSessionName(environment.id),
    provider: 'tmux',
    target_kind: terminalTargetKind(environment),
    environment_id: environment.id,
    environment_alias: environment.alias,
    working_directory: workingDirectory,
    status: 'running',
    created_at: existing?.created_at ?? timestamp,
    started_at: timestamp,
    closed_at: null,
    terminal_ws_url: createAttachmentUrl(attachmentId),
    detail: null,
    binding_id: existing?.binding_id ?? `binding-${environment.id}`,
    session_name: terminalSessionName(environment.id),
    attachment_id: attachmentId,
    attachment_expires_at: timestamp,
  };
}

function createUnavailableCodeServerStatus(
  environmentId: string | null = null,
  environmentAlias: string | null = null,
  workspaceDir: string | null = null,
  detail: string | null = 'code-server session not started'
): CodeServerStatus {
  return {
    status: 'unavailable',
    environment_id: environmentId,
    environment_alias: environmentAlias,
    workspace_dir: workspaceDir,
    detail,
    managed: true,
  };
}

function createToolStatus(
  available: boolean,
  version: string | null = null,
  path: string | null = null
): { available: boolean; version: string | null; path: string | null } {
  return { available, version, path };
}

function createMockEnvironment(
  payload: EnvironmentCreateRequest | EnvironmentUpdateRequest,
  existing?: EnvironmentRecord
): EnvironmentRecord {
  const timestamp = nowIso();
  const id = existing?.id ?? `env-${++mockEnvironmentCounter}`;
  return {
    id,
    alias: payload.alias ?? existing?.alias ?? 'mock-env',
    display_name: payload.display_name ?? existing?.display_name ?? 'Mock Environment',
    description: payload.description ?? existing?.description ?? null,
    tags: payload.tags ?? existing?.tags ?? [],
    host: payload.host ?? existing?.host ?? 'mock.example.com',
    port: payload.port ?? existing?.port ?? 22,
    user: payload.user ?? existing?.user ?? 'root',
    auth_kind: payload.auth_kind ?? existing?.auth_kind ?? 'ssh_key',
    identity_file: payload.identity_file ?? existing?.identity_file ?? null,
    proxy_jump: payload.proxy_jump ?? existing?.proxy_jump ?? null,
    proxy_command: payload.proxy_command ?? existing?.proxy_command ?? null,
    ssh_options: payload.ssh_options ?? existing?.ssh_options ?? {},
    default_workdir: payload.default_workdir ?? existing?.default_workdir ?? null,
    preferred_python: payload.preferred_python ?? existing?.preferred_python ?? null,
    preferred_env_manager: payload.preferred_env_manager ?? existing?.preferred_env_manager ?? null,
    preferred_runtime_notes: payload.preferred_runtime_notes ?? existing?.preferred_runtime_notes ?? null,
    task_harness_profile: payload.task_harness_profile ?? existing?.task_harness_profile ?? null,
    code_server_path: payload.code_server_path ?? existing?.code_server_path ?? null,
    is_seed: existing?.is_seed ?? false,
    created_at: existing?.created_at ?? timestamp,
    updated_at: timestamp,
    latest_detection: existing?.latest_detection ?? null,
  };
}

function createMockDetection(environment: EnvironmentRecord): EnvironmentRecord['latest_detection'] {
  const timestamp = nowIso();
  return {
    environment_id: environment.id,
    detected_at: timestamp,
    status: environment.is_seed ? 'failed' : 'success',
    summary: environment.is_seed
      ? 'Localhost seed profile requires a reachable SSH service.'
      : `Manual detection completed for ${environment.alias}.`,
    errors: environment.is_seed ? ['localhost_seed_unreachable'] : [],
    warnings: environment.is_seed ? ['localhost_seed_unreachable'] : [],
    ssh_ok: !environment.is_seed,
    hostname: environment.host,
    os_info: 'linux',
    arch: 'x86_64',
    workdir_exists: Boolean(environment.default_workdir),
    python: createToolStatus(
      !environment.is_seed,
      environment.is_seed ? null : environment.preferred_python ?? 'python3',
      environment.is_seed ? null : '/usr/bin/python3'
    ),
    conda: createToolStatus(false),
    uv: createToolStatus(
      !environment.is_seed,
      environment.is_seed ? null : 'mock',
      environment.is_seed ? null : '/usr/bin/uv'
    ),
    pixi: createToolStatus(false),
    code_server: createToolStatus(
      Boolean(environment.code_server_path),
      environment.code_server_path ? 'mock' : null,
      environment.code_server_path
    ),
    torch: createToolStatus(false),
    cuda: createToolStatus(false),
    gpu_models: [],
    gpu_count: 0,
    claude_cli: createToolStatus(
      !environment.is_seed,
      environment.is_seed ? null : 'mock',
      environment.is_seed ? null : '/usr/bin/claude'
    ),
    anthropic_env: 'unknown' as AnthropicEnvStatus,
  };
}

const initialMockEnvironments: EnvironmentRecord[] = [createSeedEnvironment()];
mockEnvironments = [...initialMockEnvironments];
mockWorkspaces = [createSeedWorkspace()];
mockProjects = [createSeedProject()];

export function mockGetHealth(): SystemHealth {
  return mockHealth;
}

export function mockGetTerminalSession(environmentId?: string): TerminalSession {
  if (!environmentId) {
    return createIdleTerminalSession();
  }
  const existing = mockTerminalSessions[environmentId];
  if (existing) {
    return { ...existing };
  }
  const environment = findEnvironment(environmentId);
  return {
    ...createIdleTerminalSession(environment.id, environment.alias, buildEffectiveWorkdir(environmentId)),
    target_kind: terminalTargetKind(environment),
    session_name: terminalSessionName(environment.id),
  };
}

export function mockCreateTerminalSession(environmentId: string): TerminalSession {
  const environment = findEnvironment(environmentId);
  const workingDirectory = buildEffectiveWorkdir(environmentId);
  const nextSession = createMockRunningTerminalSession(
    environment,
    workingDirectory,
    mockTerminalSessions[environmentId]
  );
  mockTerminalSessions = {
    ...mockTerminalSessions,
    [environmentId]: nextSession,
  };
  return { ...nextSession };
}

export function mockDeleteTerminalSession(
  environmentId?: string | null,
  attachmentId?: string | null
): TerminalSession {
  if (!environmentId) {
    return createIdleTerminalSession();
  }
  const current = mockTerminalSessions[environmentId];
  if (!current) {
    const environment = findEnvironment(environmentId);
    return {
      ...createIdleTerminalSession(environment.id, environment.alias, buildEffectiveWorkdir(environmentId)),
      target_kind: terminalTargetKind(environment),
      session_name: terminalSessionName(environment.id),
    };
  }
  if (attachmentId && current.attachment_id !== attachmentId) {
    return { ...current };
  }
  const detached: TerminalSession = {
    ...current,
    terminal_ws_url: null,
    attachment_id: null,
    attachment_expires_at: null,
  };
  mockTerminalSessions = {
    ...mockTerminalSessions,
    [environmentId]: detached,
  };
  return { ...detached };
}

export function mockResetTerminalSession(environmentId: string): TerminalSession {
  const environment = findEnvironment(environmentId);
  const workingDirectory = buildEffectiveWorkdir(environmentId);
  const nextSession = createMockRunningTerminalSession(
    environment,
    workingDirectory,
    mockTerminalSessions[environmentId]
  );
  mockTerminalSessions = {
    ...mockTerminalSessions,
    [environmentId]: nextSession,
  };
  return { ...nextSession };
}

export function mockGetSessionPairs(environmentId?: string): UserSessionPairListResponse {
  const environmentIds = environmentId
    ? [environmentId]
    : Array.from(
        new Set([
          ...Object.keys(mockTerminalSessions),
          ...Object.values(mockTasks).map((task) => task.environment_summary.environment_id),
        ])
      );
  const items: UserSessionPair[] = [];
  for (const currentEnvironmentId of environmentIds) {
    const environment = mockEnvironments.find((item) => item.id === currentEnvironmentId);
    if (!environment) {
      continue;
    }
    const terminalSession = mockTerminalSessions[currentEnvironmentId];
    const tasks = Object.values(mockTasks).filter(
      (task) => task.environment_summary.environment_id === currentEnvironmentId
    );
    const latestTask = tasks[0] ?? null;
    items.push({
      binding_id: terminalSession?.binding_id ?? `binding-${currentEnvironmentId}`,
      environment_id: currentEnvironmentId,
      environment_alias: environment.alias,
      personal_session_name: terminalSession?.session_name ?? terminalSessionName(currentEnvironmentId),
      agent_session_name: latestTask ? agentSessionName(currentEnvironmentId) : null,
      personal_status: terminalSession?.status ?? 'idle',
      agent_status: latestTask ? 'running' : 'idle',
      created_at: terminalSession?.created_at ?? latestTask?.created_at ?? null,
      updated_at: terminalSession?.started_at ?? latestTask?.updated_at ?? null,
      last_verified_at: latestTask?.updated_at ?? terminalSession?.started_at ?? null,
      last_personal_attach_at: terminalSession?.attachment_expires_at ?? null,
      last_agent_attach_at: latestTask?.updated_at ?? null,
      detail: null,
    });
  }
  return { items };
}

export function mockGetWorkspaces(): WorkspaceListResponse {
  return {
    items: mockWorkspaces.map((workspace) => cloneWorkspace(workspace)),
  };
}

export function mockGetWorkspace(workspaceId: string): WorkspaceRecord {
  return cloneWorkspace(findWorkspace(workspaceId));
}

export function mockCreateWorkspace(payload: WorkspaceCreateRequest): WorkspaceRecord {
  const workspace = createMockWorkspace(payload);
  mockWorkspaces = [...mockWorkspaces, workspace];
  return cloneWorkspace(workspace);
}

export function mockUpdateWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdateRequest
): WorkspaceRecord {
  const current = findWorkspace(workspaceId);
  const updated = createMockWorkspace(payload, current);
  mockWorkspaces = mockWorkspaces.map((workspace) =>
    workspace.workspace_id === workspaceId ? updated : workspace
  );
  return cloneWorkspace(updated);
}

export function mockDeleteWorkspace(workspaceId: string): void {
  findWorkspace(workspaceId);
  if (workspaceId === 'workspace-default') {
    throw new Error('Default workspace cannot be deleted');
  }
  mockWorkspaces = mockWorkspaces.filter((workspace) => workspace.workspace_id !== workspaceId);
}

export function mockGetProjects(): ProjectListResponse {
  return {
    items: mockProjects.map((project) => cloneProject(project)),
  };
}

export function mockGetProject(projectId: string): ProjectRecord {
  return cloneProject(findProject(projectId));
}

export function mockCreateProject(payload: ProjectCreateRequest): ProjectRecord {
  const project = createMockProject(payload);
  mockProjects = [...mockProjects, project];
  mockProjectEnvironmentReferences = {
    ...mockProjectEnvironmentReferences,
    [project.project_id]: [],
  };
  return cloneProject(project);
}

export function mockUpdateProject(
  projectId: string,
  payload: ProjectUpdateRequest
): ProjectRecord {
  const current = findProject(projectId);
  const updated = createMockProject(payload, current);
  mockProjects = mockProjects.map((project) =>
    project.project_id === projectId ? updated : project
  );
  return cloneProject(updated);
}

export function mockDeleteProject(projectId: string): void {
  findProject(projectId);
  if (projectId === DEFAULT_PROJECT_ID) {
    throw new Error('Default project cannot be deleted');
  }
  mockProjects = mockProjects.filter((project) => project.project_id !== projectId);
  delete mockProjectEnvironmentReferences[projectId];
}

function createMockWorkspace(
  payload: WorkspaceCreateRequest | WorkspaceUpdateRequest,
  existing?: WorkspaceRecord
): WorkspaceRecord {
  const timestamp = nowIso();
  return {
    workspace_id: existing?.workspace_id ?? `workspace-${++mockWorkspaceCounter}`,
    project_id: payload.project_id ?? existing?.project_id ?? DEFAULT_PROJECT_ID,
    label: payload.label ?? existing?.label ?? 'Mock Workspace',
    description: payload.description ?? existing?.description ?? null,
    default_workdir: payload.default_workdir ?? existing?.default_workdir ?? null,
    workspace_prompt: payload.workspace_prompt ?? existing?.workspace_prompt ?? '',
    created_at: existing?.created_at ?? timestamp,
    updated_at: timestamp,
  };
}

function createMockProject(
  payload: ProjectCreateRequest | ProjectUpdateRequest,
  existing?: ProjectRecord
): ProjectRecord {
  const timestamp = nowIso();
  return {
    project_id: existing?.project_id ?? `project-${++mockProjectCounter}`,
    name: payload.name ?? existing?.name ?? 'Mock Project',
    description: payload.description ?? existing?.description ?? null,
    default_workspace_id: payload.default_workspace_id ?? existing?.default_workspace_id ?? null,
    default_environment_id: payload.default_environment_id ?? existing?.default_environment_id ?? null,
    created_at: existing?.created_at ?? timestamp,
    updated_at: timestamp,
  };
}

export function mockGetTasks(): TaskListResponse {
  return {
    items: Object.values(mockTasks)
      .sort((left, right) => right.created_at.localeCompare(left.created_at))
      .map((task) => cloneTaskSummary(task)),
  };
}

export function mockGetTask(taskId: string): TaskRecord {
  const task = mockTasks[taskId];
  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }
  return cloneTask(task);
}

export function mockCreateTask(payload: TaskCreateRequest): TaskSummary {
  const environment = findEnvironment(payload.environment_id);
  const workspace = findWorkspace(payload.workspace_id);
  const timestamp = nowIso();
  const taskId = `task-${++mockTaskCounter}`;
  const title = payload.title?.trim() ? payload.title.trim() : deriveTaskTitle(payload.task_input);
  const resolvedWorkdir = workspace.default_workdir ?? environment.default_workdir ?? MOCK_STATE_ROOT;
  const task: TaskRecord = {
    task_id: taskId,
    project_id: payload.project_id ?? DEFAULT_PROJECT_ID,
    title,
    task_profile: payload.task_profile,
    status: 'queued',
    workspace_summary: {
      workspace_id: workspace.workspace_id,
      label: workspace.label,
      description: workspace.description,
      default_workdir: workspace.default_workdir,
    },
    environment_summary: {
      environment_id: environment.id,
      alias: environment.alias,
      display_name: environment.display_name,
      host: environment.host,
      default_workdir: environment.default_workdir,
    },
    created_at: timestamp,
    updated_at: timestamp,
    started_at: null,
    completed_at: null,
    error_summary: null,
    latest_output_seq: 1,
    binding: {
      workspace: {
        workspace_id: workspace.workspace_id,
        label: workspace.label,
        description: workspace.description,
        default_workdir: workspace.default_workdir,
      },
      environment: {
        environment_id: environment.id,
        alias: environment.alias,
        display_name: environment.display_name,
        host: environment.host,
        default_workdir: environment.default_workdir,
      },
      task_profile: payload.task_profile,
      title,
      task_input: payload.task_input,
      resolved_workdir: resolvedWorkdir,
      snapshot_path: `.ainrf/runtime/task-harness/tasks/${taskId}/binding_snapshot.json`,
    },
    prompt: {
      rendered_prompt: [
        '[Global harness/system]',
        'You are running inside AINRF Task Harness v1.',
        '',
        '[Workspace]',
        workspace.workspace_prompt,
        '',
        '[Environment]',
        environment.task_harness_profile ?? '',
        '',
        '[Task profile]',
        'Use Claude Code style execution.',
        '',
        '[Task input]',
        payload.task_input,
      ].join('\n'),
      layer_order: ['global_harness_system', 'workspace', 'environment', 'task_profile', 'task_input'],
      layers: [
        {
          position: 1,
          name: 'global_harness_system',
          label: 'Global harness/system',
          content: 'You are running inside AINRF Task Harness v1.',
          char_count: 42,
        },
        {
          position: 2,
          name: 'workspace',
          label: 'Workspace',
          content: workspace.workspace_prompt,
          char_count: workspace.workspace_prompt.length,
        },
        {
          position: 3,
          name: 'environment',
          label: 'Environment',
          content: environment.task_harness_profile ?? '',
          char_count: (environment.task_harness_profile ?? '').length,
        },
        {
          position: 4,
          name: 'task_profile',
          label: 'Task profile',
          content: 'Use Claude Code style execution.',
          char_count: 32,
        },
        {
          position: 5,
          name: 'task_input',
          label: 'Task input',
          content: payload.task_input,
          char_count: payload.task_input.length,
        },
      ],
      manifest_path: `.ainrf/runtime/task-harness/tasks/${taskId}/prompt_layer_manifest.json`,
    },
    runtime: {
      runner_kind: null,
      working_directory: resolvedWorkdir,
      command: [],
      prompt_file: `.ainrf/runtime/task-harness/tasks/${taskId}/rendered_prompt.txt`,
      helper_path: null,
      launch_payload_path: `.ainrf/runtime/task-harness/tasks/${taskId}/resolved_launch_payload.json`,
    },
    result: {
      exit_code: null,
      failure_category: null,
      error_summary: null,
      completed_at: null,
    },
  };
  mockTasks = {
    ...mockTasks,
    [taskId]: task,
  };
  mockTaskOutputs = {
    ...mockTaskOutputs,
    [taskId]: [
      {
        task_id: taskId,
        seq: 1,
        kind: 'lifecycle',
        content: 'Task queued in Task Harness v1',
        created_at: timestamp,
      },
    ],
  };
  return cloneTaskSummary(task);
}

export function mockGetTaskOutput(taskId: string, afterSeq: number = 0): TaskOutputListResponse {
  mockGetTask(taskId);
  const items = (mockTaskOutputs[taskId] ?? [])
    .filter((event) => event.seq > afterSeq)
    .map((event) => cloneTaskOutput(event));
  return {
    items,
    next_seq: items.at(-1)?.seq ?? afterSeq,
  };
}

export function mockArchiveTask(taskId: string): TaskSummary {
  const task = mockGetTask(taskId);
  const timestamp = nowIso();
  mockTasks = {
    ...mockTasks,
    [taskId]: { ...task, updated_at: timestamp },
  };
  return cloneTaskSummary(mockTasks[taskId]);
}

export function mockCancelTask(taskId: string): TaskSummary {
  const task = mockGetTask(taskId);
  if (task.status === 'succeeded' || task.status === 'failed' || task.status === 'cancelled') {
    throw new Error('Cannot cancel task in terminal state');
  }
  const timestamp = nowIso();
  mockTasks = {
    ...mockTasks,
    [taskId]: {
      ...task,
      status: 'cancelled',
      updated_at: timestamp,
      completed_at: timestamp,
      error_summary: 'Task cancelled by user',
    },
  };
  return cloneTaskSummary(mockTasks[taskId]);
}

export function mockGetCodeServerStatus(environmentId?: string): CodeServerStatus {
  if (!environmentId) {
    return { ...mockCodeServerStatus };
  }
  if (mockCodeServerStatus.environment_id === environmentId) {
    return { ...mockCodeServerStatus };
  }
  const environment = findEnvironment(environmentId);
  return createUnavailableCodeServerStatus(
    environment.id,
    environment.alias,
    buildEffectiveWorkdir(environmentId)
  );
}

export function mockCreateCodeServerSession(environmentId: string): CodeServerStatus {
  const environment = findEnvironment(environmentId);
  if (environment.auth_kind === 'password') {
    throw new Error('Workspace does not support password-auth environments');
  }
  mockCodeServerStatus = {
    status: 'ready',
    environment_id: environment.id,
    environment_alias: environment.alias,
    workspace_dir: buildEffectiveWorkdir(environmentId),
    detail: null,
    managed: true,
  };
  return { ...mockCodeServerStatus };
}

export function mockDeleteCodeServerSession(): CodeServerStatus {
  mockCodeServerStatus = createUnavailableCodeServerStatus(
    mockCodeServerStatus.environment_id,
    mockCodeServerStatus.environment_alias,
    mockCodeServerStatus.workspace_dir,
    'code-server stopped'
  );
  return { ...mockCodeServerStatus };
}

export function mockGetEnvironments(): EnvironmentListResponse {
  return {
    items: mockEnvironments.map((environment) => cloneEnvironment(environment)),
  };
}

export function mockGetEnvironment(environmentId: string): EnvironmentRecord {
  return cloneEnvironment(findEnvironment(environmentId));
}

export function mockCreateEnvironment(payload: EnvironmentCreateRequest): EnvironmentRecord {
  const environment = createMockEnvironment(payload);
  mockEnvironments = [...mockEnvironments, environment];
  return cloneEnvironment(environment);
}

export function mockUpdateEnvironment(
  environmentId: string,
  payload: EnvironmentUpdateRequest
): EnvironmentRecord {
  const current = findEnvironment(environmentId);
  const updated = createMockEnvironment(payload, current);
  mockEnvironments = mockEnvironments.map((environment) =>
    environment.id === environmentId ? updated : environment
  );
  return cloneEnvironment(updated);
}

export function mockDeleteEnvironment(environmentId: string): void {
  const current = findEnvironment(environmentId);
  if (current.is_seed) {
    throw new Error(`Environment cannot be deleted: ${environmentId}`);
  }
  const references = Object.values(mockProjectEnvironmentReferences).flat();
  if (references.some((reference) => reference.environment_id === environmentId)) {
    throw new Error(`Environment is still referenced by a project: ${environmentId}`);
  }
  mockEnvironments = mockEnvironments.filter((environment) => environment.id !== environmentId);
}

export function mockDetectEnvironment(environmentId: string): EnvironmentRecord {
  const current = findEnvironment(environmentId);
  const updated = {
    ...current,
    latest_detection: createMockDetection(current),
    updated_at: nowIso(),
  };
  mockEnvironments = mockEnvironments.map((environment) =>
    environment.id === environmentId ? updated : environment
  );
  return cloneEnvironment(updated);
}

export function mockInstallEnvironmentCodeServer(
  environmentId: string
): EnvironmentCodeServerInstallResponse {
  const current = findEnvironment(environmentId);
  const version = '4.117.0';
  const installDir = `~/.local/ainrf/code-server/code-server-${version}-linux-amd64`;
  const codeServerPath = `${installDir}/bin/code-server`;
  const alreadyInstalled = current.code_server_path === codeServerPath;
  const updated: EnvironmentRecord = {
    ...current,
    code_server_path: codeServerPath,
    updated_at: nowIso(),
  };
  mockEnvironments = mockEnvironments.map((environment) =>
    environment.id === environmentId ? updated : environment
  );
  return {
    environment: cloneEnvironment(updated),
    installed: !alreadyInstalled,
    version,
    install_dir: installDir,
    code_server_path: codeServerPath,
    execution_mode: 'ssh',
    already_installed: alreadyInstalled,
    detail: alreadyInstalled ? 'code-server already installed' : 'code-server installed',
  };
}

export function mockGetProjectEnvironmentReferences(
  projectId: string = DEFAULT_PROJECT_ID
): ProjectEnvironmentReferenceListResponse {
  return {
    items: getProjectReferences(projectId).map((reference) => cloneProjectReference(reference)),
  };
}

export function mockCreateProjectEnvironmentReference(
  projectId: string,
  payload: ProjectEnvironmentReferenceCreateRequest
): ProjectEnvironmentReference {
  findEnvironment(payload.environment_id);
  if (findProjectReference(projectId, payload.environment_id)) {
    throw new Error(`Environment is already referenced by this project: ${payload.environment_id}`);
  }
  const reference: ProjectEnvironmentReference = {
    environment_id: payload.environment_id,
    is_default: payload.is_default ?? false,
    override_workdir: payload.override_workdir ?? null,
    override_env_name: payload.override_env_name ?? null,
    override_env_manager: payload.override_env_manager ?? null,
    override_runtime_notes: payload.override_runtime_notes ?? null,
    updated_at: nowIso(),
  };
  return cloneProjectReference(replaceProjectReference(projectId, reference));
}

export function mockUpdateProjectEnvironmentReference(
  projectId: string,
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest
): ProjectEnvironmentReference {
  const current = findProjectReference(projectId, environmentId);
  if (!current) {
    throw new Error(`Project environment reference not found: ${environmentId}`);
  }
  const next: ProjectEnvironmentReference = {
    environment_id: environmentId,
    is_default: payload.is_default ?? current.is_default,
    override_workdir:
      payload.override_workdir !== undefined ? payload.override_workdir : current.override_workdir,
    override_env_name:
      payload.override_env_name !== undefined ? payload.override_env_name : current.override_env_name,
    override_env_manager:
      payload.override_env_manager !== undefined
        ? payload.override_env_manager
        : current.override_env_manager,
    override_runtime_notes:
      payload.override_runtime_notes !== undefined
        ? payload.override_runtime_notes
        : current.override_runtime_notes,
    updated_at: nowIso(),
  };
  return cloneProjectReference(replaceProjectReference(projectId, next));
}

export function mockDeleteProjectEnvironmentReference(
  projectId: string,
  environmentId: string
): void {
  const current = findProjectReference(projectId, environmentId);
  if (!current) {
    throw new Error(`Project environment reference not found: ${environmentId}`);
  }
  removeProjectReference(projectId, environmentId);
}

export function resetMockTerminalSession(): TerminalSession {
  mockTerminalSessions = {};
  mockTerminalAttachmentCounter = 0;
  mockTaskCounter = 0;
  mockTasks = {};
  mockTaskOutputs = {};
  return createIdleTerminalSession();
}

export function resetMockEnvironmentState(): EnvironmentListResponse {
  mockEnvironmentCounter = 0;
  mockTerminalAttachmentCounter = 0;
  mockTaskCounter = 0;
  mockWorkspaceCounter = 0;
  mockProjectCounter = 0;
  mockEnvironments = [...initialMockEnvironments];
  mockWorkspaces = [createSeedWorkspace()];
  mockProjects = [createSeedProject()];
  mockProjectEnvironmentReferences = { [DEFAULT_PROJECT_ID]: [] };
  mockTerminalSessions = {};
  mockTasks = {};
  mockTaskOutputs = {};
  mockCodeServerStatus = createUnavailableCodeServerStatus();
  return mockGetEnvironments();
}

export function resetMockTaskState(): TaskListResponse {
  mockTaskCounter = 0;
  mockTasks = {};
  mockTaskOutputs = {};
  return mockGetTasks();
}

const mockSkills: SkillItem[] = [
  { skill_id: 'web-search', label: '网络搜索', description: '使用网络搜索获取实时信息' },
  { skill_id: 'code-analysis', label: '代码分析', description: '分析代码结构和质量' },
  { skill_id: 'citation', label: '引用管理', description: '管理学术引用和参考文献' },
  { skill_id: 'repo-inspection', label: '仓库检查', description: '检查代码仓库结构和状态' },
  { skill_id: 'paper-reading', label: '论文阅读', description: '阅读和理解学术论文' },
  { skill_id: 'writing', label: '学术写作', description: '协助学术写作和润色' },
];

export function mockGetSkills(): SkillListResponse {
  return { items: mockSkills.map((skill) => ({ ...skill })) };
}

export function mockListFiles(_environmentId: string, path: string = ''): FileListResponse {
  const rootPath = path || '/workspace/project';
  return {
    path: rootPath,
    entries: [
      { name: 'src', path: `${rootPath}/src`, kind: 'directory', size: null, modified_at: null },
      { name: 'tests', path: `${rootPath}/tests`, kind: 'directory', size: null, modified_at: null },
      { name: 'README.md', path: `${rootPath}/README.md`, kind: 'file', size: 1240, modified_at: '2026-04-29T10:00:00Z' },
      { name: 'package.json', path: `${rootPath}/package.json`, kind: 'file', size: 850, modified_at: '2026-04-29T10:00:00Z' },
      { name: '.gitignore', path: `${rootPath}/.gitignore`, kind: 'file', size: 120, modified_at: '2026-04-29T10:00:00Z' },
    ],
  };
}

export function mockReadFile(_environmentId: string, path: string): FileReadResponse {
  const name = path.split('/').pop() || '';
  if (name.endsWith('.png') || name.endsWith('.jpg')) {
    return {
      path,
      content: 'iVBORw0KGgo=', // dummy base64
      is_binary: true,
      size: 1024,
      language: null,
      mime_type: name.endsWith('.png') ? 'image/png' : 'image/jpeg',
    };
  }
  const language = name.endsWith('.py') ? 'python'
    : name.endsWith('.js') ? 'javascript'
    : name.endsWith('.ts') ? 'typescript'
    : name.endsWith('.json') ? 'json'
    : name.endsWith('.md') ? 'markdown'
    : null;
  return {
    path,
    content: `// Content of ${name}\nconsole.log('hello');`,
    is_binary: false,
    size: 64,
    language,
    mime_type: null,
  };
}
