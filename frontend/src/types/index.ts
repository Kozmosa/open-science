export interface RuntimeDependencyStatus {
  available: boolean;
  path: string | null;
  detail: string | null;
}

export interface RuntimeReadiness {
  ready: boolean;
  dependencies: {
    tmux: RuntimeDependencyStatus;
    uv: RuntimeDependencyStatus;
    code_server: RuntimeDependencyStatus;
  };
}

export interface SystemHealth {
  status: 'ok' | 'degraded';
  state_root: string;
  startup_cwd: string;
  default_workspace_dir: string;
  container_configured: boolean;
  container_health?: {
    ssh_ok: boolean;
    claude_ok: boolean;
    project_dir_writable: boolean;
    claude_version: string | null;
    gpu_models: string[];
    cuda_version: string | null;
    disk_free_bytes: number | null;
    warnings: string[];
  } | null;
  runtime_readiness?: RuntimeReadiness | null;
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

export type TerminalAttachmentMode = 'write' | 'observe';

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

export type TaskStatus = 'queued' | 'starting' | 'running' | 'succeeded' | 'failed';
export type TaskOutputKind = 'stdout' | 'stderr' | 'system' | 'lifecycle';

export interface WorkspaceRecord {
  workspace_id: string;
  label: string;
  description: string | null;
  default_workdir: string | null;
  workspace_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceListResponse {
  items: WorkspaceRecord[];
}

export interface WorkspaceCreateRequest {
  label: string;
  description?: string | null;
  default_workdir?: string | null;
  workspace_prompt: string;
}

export interface WorkspaceUpdateRequest {
  label?: string | null;
  description?: string | null;
  default_workdir?: string | null;
  workspace_prompt?: string | null;
}

export interface WorkspaceSummary {
  workspace_id: string;
  label: string;
  description: string | null;
  default_workdir: string | null;
}

export interface TaskEnvironmentSummary {
  environment_id: string;
  alias: string;
  display_name: string;
  host: string;
  default_workdir: string | null;
}

export interface TaskSummary {
  task_id: string;
  title: string;
  task_profile: string;
  status: TaskStatus;
  workspace_summary: WorkspaceSummary;
  environment_summary: TaskEnvironmentSummary;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_summary: string | null;
  latest_output_seq: number;
}

export interface ResearchAgentProfileSnapshot {
  profile_id: string;
  label: string;
  system_prompt: string | null;
  skills_prompt: string | null;
  settings_json: Record<string, unknown> | null;
  settings_artifact_path: string | null;
}

export interface TaskConfigurationSnapshot {
  mode: 'raw_prompt' | 'structured_research';
  template_id: string | null;
  template_vars: Record<string, unknown>;
  raw_prompt: string | null;
  rendered_task_input: string;
}

export interface TaskBindingSummary {
  workspace: WorkspaceSummary;
  environment: TaskEnvironmentSummary;
  task_profile: string;
  title: string;
  task_input: string;
  resolved_workdir: string;
  snapshot_path: string;
  execution_engine?: string;
  research_agent_profile?: ResearchAgentProfileSnapshot | null;
  task_configuration?: TaskConfigurationSnapshot | null;
}

export interface TaskPromptLayer {
  position: number;
  name: string;
  label: string;
  content: string;
  char_count: number;
}

export interface TaskPromptSummary {
  rendered_prompt: string;
  layer_order: string[];
  layers: TaskPromptLayer[];
  manifest_path: string;
}

export interface TaskRuntimeSummary {
  runner_kind: string | null;
  working_directory: string | null;
  command: string[];
  prompt_file: string | null;
  helper_path: string | null;
  launch_payload_path: string | null;
}

export interface TaskResultSummary {
  exit_code: number | null;
  failure_category: string | null;
  error_summary: string | null;
  completed_at: string | null;
}

export interface TaskRecord extends TaskSummary {
  binding: TaskBindingSummary | null;
  prompt: TaskPromptSummary | null;
  runtime: TaskRuntimeSummary | null;
  result: TaskResultSummary;
  execution_engine?: string;
  research_agent_profile?: ResearchAgentProfileSnapshot | null;
  task_configuration?: TaskConfigurationSnapshot | null;
}

export interface TaskListResponse {
  items: TaskSummary[];
}

export interface TaskCreateRequest {
  workspace_id: string;
  environment_id: string;
  task_profile: string;
  task_input: string;
  title?: string | null;
  execution_engine?: string | null;
  research_agent_profile?: {
    profile_id: string;
    label: string;
    system_prompt?: string | null;
    skills_prompt?: string | null;
    settings_json?: Record<string, unknown> | null;
  } | null;
  task_configuration?: {
    mode: 'raw_prompt' | 'structured_research';
    template_id?: string | null;
    template_vars?: Record<string, unknown>;
    raw_prompt?: string | null;
  } | null;
}

export interface TaskOutputEvent {
  task_id: string;
  seq: number;
  kind: TaskOutputKind;
  content: string;
  created_at: string;
}

export interface TaskOutputListResponse {
  items: TaskOutputEvent[];
  next_seq: number;
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
  task_harness_profile: string | null;
  code_server_path: string | null;
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
  task_harness_profile?: string | null;
  code_server_path?: string | null;
}

export interface EnvironmentCodeServerInstallResponse {
  environment: EnvironmentRecord;
  installed: boolean;
  version: string;
  install_dir: string;
  code_server_path: string;
  execution_mode: 'ssh' | 'personal_tmux_fallback';
  already_installed: boolean;
  detail: string;
  terminal_session_id?: string | null;
  terminal_attachment_id?: string | null;
  terminal_ws_url?: string | null;
  terminal_attachment_expires_at?: string | null;
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
  task_harness_profile?: string | null;
  code_server_path?: string | null;
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
