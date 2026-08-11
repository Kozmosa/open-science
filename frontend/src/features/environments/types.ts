import type {
  EnvironmentAuthKind,
  EnvironmentDetectionResponse,
  EnvironmentCreateRequest,
  EnvironmentResponse,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceResponse,
  ProjectEnvironmentReferenceUpdateRequest,
} from '@/generated/transport';

export type { EnvironmentAuthKind } from '@/generated/transport';

export type EnvironmentDetectionStatus = EnvironmentDetectionResponse['status'];
export type AnthropicEnvStatus = EnvironmentDetectionResponse['anthropic_env'];

export type ToolStatus = {
  available: boolean;
  version: string | null;
  path: string | null;
};

export type EnvironmentDetection = {
  environment_id: string;
  detected_at: string;
  status: EnvironmentDetectionStatus;
  summary: string;
  errors: string[];
  warnings: string[];
  ssh_ok: boolean;
  tmux_ok: boolean;
  hostname: string | null;
  os_info: string | null;
  arch: string | null;
  workdir_exists: boolean | null;
  python: ToolStatus;
  conda: ToolStatus;
  uv: ToolStatus;
  pixi: ToolStatus;
  codex: ToolStatus;
  torch: ToolStatus;
  cuda: ToolStatus;
  gpu_models: string[];
  gpu_count: number;
  claude_cli: ToolStatus;
  anthropic_env: AnthropicEnvStatus;
};

export type EnvironmentRecord = {
  id: string;
  alias: string;
  display_name: string;
  description: string | null;
  is_seed: boolean;
  tags: string[];
  host: string;
  port: number;
  user: string;
  auth_kind: EnvironmentAuthKind;
  identity_file: string | null;
  proxy_jump: string | null;
  proxy_command: string | null;
  ssh_options: Record<string, string>;
  default_workdir: string | null;
  preferred_python: string | null;
  preferred_env_manager: string | null;
  preferred_runtime_notes: string | null;
  task_harness_profile: string | null;
  created_at: string | null;
  updated_at: string | null;
  latest_detection: EnvironmentDetection | null;
};

export type EnvironmentListResponse = { items: EnvironmentRecord[] };

export type ProjectEnvironmentReference = {
  environment_id: string;
  is_default: boolean;
  override_workdir: string | null;
  override_env_name: string | null;
  override_env_manager: string | null;
  override_runtime_notes: string | null;
  updated_at: string | null;
};

export type ProjectEnvironmentReferenceListResponse = {
  items: ProjectEnvironmentReference[];
};

export type EnvironmentMutationInput = {
  alias: string;
  displayName: string;
  description: string | null;
  tags: string[];
  host: string;
  port: number;
  user: string;
  authKind: EnvironmentAuthKind;
  identityFile: string | null;
  proxyJump: string | null;
  proxyCommand: string | null;
  sshOptions: Record<string, string>;
  defaultWorkdir: string | null;
  preferredPython: string | null;
  preferredEnvManager: string | null;
  preferredRuntimeNotes: string | null;
  taskHarnessProfile: string | null;
};

export type ProjectEnvironmentReferenceUpdateInput = {
  isDefault?: boolean;
  overrideWorkdir: string | null;
  overrideEnvName: string | null;
  overrideEnvManager: string | null;
  overrideRuntimeNotes: string | null;
};

export type ProjectEnvironmentReferenceCreateInput = ProjectEnvironmentReferenceUpdateInput & {
  environmentId: string;
};

export function toEnvironmentCreateRequest(value: EnvironmentMutationInput): EnvironmentCreateRequest {
  return {
    alias: value.alias,
    display_name: value.displayName,
    description: value.description,
    tags: value.tags,
    host: value.host,
    port: value.port,
    user: value.user,
    auth_kind: value.authKind,
    identity_file: value.identityFile,
    proxy_jump: value.proxyJump,
    proxy_command: value.proxyCommand,
    ssh_options: value.sshOptions,
    default_workdir: value.defaultWorkdir,
    preferred_python: value.preferredPython,
    preferred_env_manager: value.preferredEnvManager,
    preferred_runtime_notes: value.preferredRuntimeNotes,
    task_harness_profile: value.taskHarnessProfile,
  };
}

export function toEnvironmentUpdateRequest(value: EnvironmentMutationInput): EnvironmentUpdateRequest {
  return toEnvironmentCreateRequest(value);
}

export function toProjectEnvironmentReferenceUpdateRequest(value: ProjectEnvironmentReferenceUpdateInput): ProjectEnvironmentReferenceUpdateRequest {
  return {
    is_default: value.isDefault ?? false,
    override_workdir: value.overrideWorkdir,
    override_env_name: value.overrideEnvName,
    override_env_manager: value.overrideEnvManager,
    override_runtime_notes: value.overrideRuntimeNotes,
  };
}

export function toProjectEnvironmentReferenceCreateRequest(value: ProjectEnvironmentReferenceCreateInput): ProjectEnvironmentReferenceCreateRequest {
  return {
    environment_id: value.environmentId,
    is_default: value.isDefault ?? false,
    override_workdir: value.overrideWorkdir,
    override_env_name: value.overrideEnvName,
    override_env_manager: value.overrideEnvManager,
    override_runtime_notes: value.overrideRuntimeNotes,
  };
}

function adaptToolStatus(value: { available: boolean; version?: string | null; path?: string | null }): ToolStatus {
  return { available: value.available, version: value.version ?? null, path: value.path ?? null };
}

function adaptDetection(value: EnvironmentDetectionResponse | null | undefined): EnvironmentDetection | null {
  if (!value) return null;
  return {
    environment_id: value.environment_id,
    detected_at: value.detected_at,
    status: value.status,
    summary: value.summary,
    errors: value.errors ?? [],
    warnings: value.warnings ?? [],
    ssh_ok: value.ssh_ok ?? false,
    tmux_ok: value.tmux_ok ?? false,
    hostname: value.hostname ?? null,
    os_info: value.os_info ?? null,
    arch: value.arch ?? null,
    workdir_exists: value.workdir_exists ?? null,
    python: adaptToolStatus(value.python),
    conda: adaptToolStatus(value.conda),
    uv: adaptToolStatus(value.uv),
    pixi: adaptToolStatus(value.pixi),
    codex: adaptToolStatus(value.codex),
    torch: adaptToolStatus(value.torch),
    cuda: adaptToolStatus(value.cuda),
    gpu_models: value.gpu_models ?? [],
    gpu_count: value.gpu_count ?? 0,
    claude_cli: adaptToolStatus(value.claude_cli),
    anthropic_env: value.anthropic_env,
  };
}

export function adaptEnvironment(value: EnvironmentResponse): EnvironmentRecord {
  return {
    id: value.id,
    alias: value.alias,
    display_name: value.display_name,
    description: value.description ?? null,
    is_seed: value.is_seed ?? false,
    tags: value.tags ?? [],
    host: value.host,
    port: value.port ?? 22,
    user: value.user ?? 'root',
    auth_kind: value.auth_kind ?? 'ssh_key',
    identity_file: value.identity_file ?? null,
    proxy_jump: value.proxy_jump ?? null,
    proxy_command: value.proxy_command ?? null,
    ssh_options: value.ssh_options ?? {},
    default_workdir: value.default_workdir ?? null,
    preferred_python: value.preferred_python ?? null,
    preferred_env_manager: value.preferred_env_manager ?? null,
    preferred_runtime_notes: value.preferred_runtime_notes ?? null,
    task_harness_profile: value.task_harness_profile ?? null,
    created_at: value.created_at ?? null,
    updated_at: value.updated_at ?? null,
    latest_detection: adaptDetection(value.latest_detection),
  };
}

export function adaptEnvironmentList(value: { items: EnvironmentResponse[] }): EnvironmentListResponse {
  return { items: value.items.map(adaptEnvironment) };
}

export function adaptProjectEnvironmentReference(value: ProjectEnvironmentReferenceResponse): ProjectEnvironmentReference {
  return {
    environment_id: value.environment_id,
    is_default: value.is_default ?? false,
    override_workdir: value.override_workdir ?? null,
    override_env_name: value.override_env_name ?? null,
    override_env_manager: value.override_env_manager ?? null,
    override_runtime_notes: value.override_runtime_notes ?? null,
    updated_at: value.updated_at ?? null,
  };
}

export function adaptProjectEnvironmentReferenceList(value: { items: ProjectEnvironmentReferenceResponse[] }): ProjectEnvironmentReferenceListResponse {
  return { items: value.items.map(adaptProjectEnvironmentReference) };
}
