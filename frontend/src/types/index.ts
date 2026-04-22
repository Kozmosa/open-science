export interface SystemHealth {
  status: 'ok' | 'degraded';
  state_root: string;
  container_configured: boolean;
  container_health?: {
    ssh_ok: boolean;
    claude_ok: boolean;
    anthropic_api_key_ok: boolean;
    project_dir_writable: boolean;
    claude_version: string | null;
    gpu_models: string[];
    cuda_version: string | null;
    disk_free_bytes: number | null;
    warnings: string[];
  } | null;
  detail?: string | null;
}

export type TerminalSessionStatus = 'idle' | 'starting' | 'running' | 'stopping' | 'failed';

export interface TerminalSession {
  session_id: string | null;
  provider: 'pty' | 'tmux';
  target_kind: string;
  environment_id: string | null;
  environment_alias: string | null;
  working_directory: string | null;
  status: TerminalSessionStatus;
  created_at: string | null;
  started_at: string | null;
  closed_at: string | null;
  terminal_ws_url: string | null;
  detail: string | null;
  binding_id: string | null;
  session_name: string | null;
  attachment_id: string | null;
  attachment_expires_at: string | null;
}

export type TerminalAttachmentMode = 'interactive' | 'observe';
export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface UserSessionPair {
  binding_id: string;
  environment_id: string;
  environment_alias: string | null;
  personal_session_name: string;
  agent_session_name: string | null;
  personal_status: TerminalSessionStatus;
  agent_status: TerminalSessionStatus | null;
  created_at: string | null;
  updated_at: string | null;
  last_verified_at: string | null;
  last_personal_attach_at: string | null;
  last_agent_attach_at: string | null;
  detail: string | null;
}

export interface UserSessionPairListResponse {
  items: UserSessionPair[];
}

export interface TaskTerminalBinding {
  task_id: string;
  binding_id: string;
  environment_id: string;
  agent_session_name: string;
  window_id: string;
  window_name: string;
  status: TaskStatus;
  mode: TerminalAttachmentMode;
  readonly: boolean;
  last_output_at: string | null;
}

export interface TaskRecord {
  task_id: string;
  binding_id: string;
  environment_id: string;
  environment_alias: string | null;
  title: string;
  command: string;
  working_directory: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  exit_code: number | null;
  detail: string | null;
  terminal: TaskTerminalBinding | null;
}

export interface TaskListResponse {
  items: TaskRecord[];
}

export interface TaskCreateRequest {
  environment_id: string;
  title: string;
  command: string;
  working_directory?: string | null;
}

export interface TerminalAttachment {
  attachment_id: string;
  terminal_ws_url: string;
  expires_at: string;
  binding_id: string;
  session_id: string;
  session_name: string;
  environment_id: string;
  environment_alias: string;
  target_kind: string;
  working_directory: string | null;
  readonly: boolean;
  mode: TerminalAttachmentMode;
  window_id: string | null;
  window_name: string | null;
}

export type CodeServerLifecycleStatus = 'starting' | 'ready' | 'unavailable';

export interface CodeServerStatus {
  status: CodeServerLifecycleStatus;
  environment_id: string | null;
  environment_alias: string | null;
  workspace_dir: string | null;
  detail: string | null;
  managed: boolean;
}

export type EnvironmentAuthKind = 'ssh_key' | 'password' | 'agent';
export type EnvironmentDetectionStatus = 'success' | 'partial' | 'failed';
export type AnthropicEnvStatus = 'present' | 'missing' | 'unknown';

export interface ToolStatus {
  available: boolean;
  version: string | null;
  path: string | null;
}

export interface EnvironmentDetection {
  environment_id: string;
  detected_at: string;
  status: EnvironmentDetectionStatus;
  summary: string;
  errors: string[];
  warnings: string[];
  ssh_ok: boolean;
  hostname: string | null;
  os_info: string | null;
  arch: string | null;
  workdir_exists: boolean | null;
  python: ToolStatus;
  conda: ToolStatus;
  uv: ToolStatus;
  pixi: ToolStatus;
  torch: ToolStatus;
  cuda: ToolStatus;
  gpu_models: string[];
  gpu_count: number;
  claude_cli: ToolStatus;
  anthropic_env: AnthropicEnvStatus;
}

export interface EnvironmentRecord {
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
  created_at: string | null;
  updated_at: string | null;
  latest_detection: EnvironmentDetection | null;
}

export interface EnvironmentListResponse {
  items: EnvironmentRecord[];
}

export interface ProjectEnvironmentReference {
  environment_id: string;
  is_default: boolean;
  override_workdir: string | null;
  override_env_name: string | null;
  override_env_manager: string | null;
  override_runtime_notes: string | null;
  updated_at: string | null;
}

export interface ProjectEnvironmentReferenceListResponse {
  items: ProjectEnvironmentReference[];
}

export interface EnvironmentCreateRequest {
  alias: string;
  display_name: string;
  host: string;
  description?: string | null;
  tags?: string[];
  port?: number;
  user?: string;
  auth_kind?: EnvironmentAuthKind;
  identity_file?: string | null;
  proxy_jump?: string | null;
  proxy_command?: string | null;
  ssh_options?: Record<string, string>;
  default_workdir?: string | null;
  preferred_python?: string | null;
  preferred_env_manager?: string | null;
  preferred_runtime_notes?: string | null;
}

export interface EnvironmentUpdateRequest {
  alias?: string | null;
  display_name?: string | null;
  host?: string | null;
  description?: string | null;
  tags?: string[] | null;
  port?: number | null;
  user?: string | null;
  auth_kind?: EnvironmentAuthKind | null;
  identity_file?: string | null;
  proxy_jump?: string | null;
  proxy_command?: string | null;
  ssh_options?: Record<string, string> | null;
  default_workdir?: string | null;
  preferred_python?: string | null;
  preferred_env_manager?: string | null;
  preferred_runtime_notes?: string | null;
}

export interface ProjectEnvironmentReferenceCreateRequest {
  environment_id: string;
  is_default?: boolean;
  override_workdir?: string | null;
  override_env_name?: string | null;
  override_env_manager?: string | null;
  override_runtime_notes?: string | null;
}

export interface ProjectEnvironmentReferenceUpdateRequest {
  is_default?: boolean | null;
  override_workdir?: string | null;
  override_env_name?: string | null;
  override_env_manager?: string | null;
  override_runtime_notes?: string | null;
}
