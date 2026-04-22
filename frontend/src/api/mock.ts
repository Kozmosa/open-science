import type {
  AnthropicEnvStatus,
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
  TerminalSession,
} from '../types';

const DEFAULT_PROJECT_ID = 'default';
const MOCK_STATE_ROOT = '.ainrf';

const mockHealth: SystemHealth = {
  status: 'ok',
  state_root: MOCK_STATE_ROOT,
  container_configured: true,
  container_health: {
    ssh_ok: true,
    claude_ok: true,
    anthropic_api_key_ok: true,
    project_dir_writable: true,
    claude_version: 'mock',
    gpu_models: ['Mock GPU'],
    cuda_version: 'mock',
    disk_free_bytes: 1024 * 1024 * 1024,
    warnings: [],
  },
  detail: null,
};

let mockEnvironmentCounter = 0;
let mockTerminalAttachmentCounter = 0;
let mockEnvironments: EnvironmentRecord[] = [];
let mockProjectEnvironmentReferences: Record<string, ProjectEnvironmentReference[]> = {
  [DEFAULT_PROJECT_ID]: [],
};
let mockTerminalSessions: Record<string, TerminalSession> = {};
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
    created_at: timestamp,
    updated_at: timestamp,
    latest_detection: null,
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

function terminalSessionName(environmentId: string): string {
  return `ainrf:u:mock-daemon:e:${environmentId}:personal`;
}

function createAttachmentUrl(attachmentId: string): string {
  return `ws://127.0.0.1:8000/terminal/attachments/${attachmentId}/ws?token=mock-token-${attachmentId}`;
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
  return createIdleTerminalSession();
}

export function resetMockEnvironmentState(): EnvironmentListResponse {
  mockEnvironmentCounter = 0;
  mockTerminalAttachmentCounter = 0;
  mockEnvironments = [...initialMockEnvironments];
  mockProjectEnvironmentReferences = { [DEFAULT_PROJECT_ID]: [] };
  mockTerminalSessions = {};
  mockCodeServerStatus = createUnavailableCodeServerStatus();
  return mockGetEnvironments();
}
