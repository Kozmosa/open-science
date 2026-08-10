import type {
  ForkPreviewResponse,
  TaskCreateRequest,
  TaskSummaryResponse,
  TurnItemResponse,
  TurnResponse,
} from '@/generated/transport';

export type TaskStatus =
  | 'queued' | 'starting' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'paused'
  | 'launch_unknown' | 'stopped_by_project_archive' | 'stopped_permission_revoked' | 'stopped_runtime_unknown';
export type TaskWorkStatus = 'open' | 'completed' | 'cancelled';
export type TaskOutputKind = 'stdout' | 'stderr' | 'system' | 'lifecycle' | 'message' | 'thinking' | 'tool_call' | 'tool_result';
export type ResearcherType = 'vanilla' | 'aris-researcher';
export type HarnessEngine = 'claude-code' | 'agent-sdk' | 'codex-app-server';
export type ForkEngineFamily = 'codex' | 'claude';
export type ForkHarnessEngine = HarnessEngine;
export type ForkTransferMode = 'selected_turns' | 'recent_turns' | 'full_transcript' | 'context_only';

export type ForkPreview = {
  preview_id: string;
  preview_hash: string;
  source_task_id: string;
  source_revision: string;
  source_engine_family: ForkEngineFamily;
  target_engine_family: ForkEngineFamily;
  target_project_id: string;
  target_workspace_id: string;
  target_harness_engine: ForkHarnessEngine;
  target_title: string;
  transfer_mode: ForkTransferMode;
  truncated: boolean;
  expires_at: string;
};

export const FORK_HARNESS_ENGINES_BY_FAMILY: Record<ForkEngineFamily, readonly ForkHarnessEngine[]> = {
  codex: ['codex-app-server'],
  claude: ['agent-sdk', 'claude-code'],
};

export function engineFamilyForHarnessEngine(engine: string): ForkEngineFamily | null {
  if (engine === 'codex-app-server') return 'codex';
  if (engine === 'agent-sdk' || engine === 'claude-code') return 'claude';
  return null;
}

export function adaptForkPreview(value: ForkPreviewResponse): ForkPreview {
  return value;
}

export type TaskCreateInput = {
  projectId: string;
  workspaceId: string;
  researcherType: ResearcherType;
  harnessEngine: HarnessEngine;
  prompt: string;
  skills: string[];
  mcpServers: string[];
  title?: string;
};

export type WorkspaceSummary = { workspace_id: string; label: string; description: string | null; default_workdir: string | null };
export type TaskEnvironmentSummary = { environment_id: string; alias: string; display_name: string; host: string; default_workdir: string | null };
export type ResearchAgentProfileSnapshot = { profile_id: string; label: string; system_prompt: string | null; skills: string[]; skills_prompt: string | null; settings_json: Record<string, unknown> | null; settings_artifact_path: string | null; model: string | null; permission_mode: string | null; max_turns: number | null; max_budget_usd: number | null; mcp_servers: Record<string, unknown> | null; disallowed_tools: string[] | null; api_base_url: string | null; api_key: string | null; default_opus_model: string | null; default_sonnet_model: string | null; default_haiku_model: string | null; env_overrides: Record<string, string> | null; codex_base_url: string | null; codex_api_key: string | null; codex_model: string | null; codex_app_server_command: string | null; codex_approval_policy: string | null; codex_config_toml: string | null; codex_auth_json: string | null };
export type TaskConfigurationSnapshot = { mode: 'raw_prompt' | 'structured_research' | 'reproduce_baseline' | 'discover_ideas' | 'validate_ideas'; template_id: string | null; template_vars: Record<string, unknown>; raw_prompt: string | null; rendered_task_input: string };
export type TaskBindingSummary = { workspace: WorkspaceSummary; environment: TaskEnvironmentSummary; task_profile: string; title: string; task_input: string; resolved_workdir: string; snapshot_path: string; execution_engine?: string; research_agent_profile?: ResearchAgentProfileSnapshot | null; task_configuration?: TaskConfigurationSnapshot | null };
export type TaskPromptLayer = { position: number; name: string; label: string; content: string; char_count: number };
export type TaskPromptSummary = { rendered_prompt: string; layer_order: string[]; layers: TaskPromptLayer[]; manifest_path: string };
export type TaskRuntimeSummary = { runner_kind: string | null; working_directory: string | null; command: string[]; prompt_file: string | null; helper_path: string | null; launch_payload_path: string | null; codex_home: string | null };
export type TaskResultSummary = { exit_code: number | null; failure_category: string | null; error_summary: string | null; completed_at: string | null };

export type TaskSummary = TaskSummaryResponse & {
  status: TaskStatus;
  work_status: TaskWorkStatus;
  started_at: string | null;
  completed_at: string | null;
  error_summary: string | null;
  prompt: string;
  task_profile?: string;
  workspace_summary?: WorkspaceSummary;
  environment_summary?: TaskEnvironmentSummary;
  binding?: TaskBindingSummary | null;
  prompt_detail?: TaskPromptSummary | null;
  runtime?: TaskRuntimeSummary | null;
  result?: TaskResultSummary;
  execution_engine?: string;
  research_agent_profile?: ResearchAgentProfileSnapshot | null;
  task_configuration?: TaskConfigurationSnapshot | null;
};
export type TaskListResponse = { items: TaskSummary[]; total?: number; has_more?: boolean; next_cursor?: string | null };
export type TaskEdge = { edge_id: string; project_id: string; source_task_id: string; target_task_id: string; relationship_type: 'derived_from' | 'depends_on' | 'related_to' | string; created_at: string };
export type TaskEdgeListResponse = { items: TaskEdge[] };
export type TaskOutputEvent = { task_id: string; seq: number; kind: TaskOutputKind; content: string; created_at: string };
export type TaskOutputListResponse = { items: TaskOutputEvent[]; next_seq: number; has_more: boolean };
export type MessageItem = { id: string; type: 'user' | 'assistant' | 'thinking' | 'tool_call' | 'tool_result' | 'system_event'; content: string | Record<string, unknown>; metadata: { timestamp: string; sequence: number; isFolded?: boolean; engineType?: string; blockId?: string; isStreaming?: boolean; isDelta?: boolean; sourceKind?: TaskOutputKind } };
export type DisplayMessageItem = { kind: 'single'; message: MessageItem } | { kind: 'group'; id: string; messages: MessageItem[]; collapsed: boolean };
export type TaskMessagesResponse = { messages: MessageItem[]; has_more: boolean; next_sequence: number | null };
export type TaskTurn = {
  status: string;
  task_id: string;
  turn_id: string;
  turn_seq: number;
  started_at: string | null;
  finished_at: string | null;
  failure_code: string | null;
  token_usage_json: string | null;
  context_snapshot_ref: string | null;
};
export type TaskTurnItem = {
  actor: string;
  item_id: string;
  item_type: string;
  payload: Record<string, unknown>;
  task_id: string;
  task_item_seq: number;
  turn_id: string;
  turn_item_seq: number;
  persisted_at: string | null;
};
export type TaskTurnListResponse = { items: TaskTurn[] };
export type TaskTurnItemListResponse = { items: TaskTurnItem[] };
export type TokenUsage = { total: { input_tokens: number; output_tokens: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number; cost_usd?: number }; by_model?: Record<string, { input_tokens: number; output_tokens: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number; cost_usd?: number }>; source: 'agent-sdk' | 'claude-session-meta' };

export function toTaskCreateRequest(value: TaskCreateInput): TaskCreateRequest {
  return {
    project_id: value.projectId,
    workspace_id: value.workspaceId,
    researcher_type: value.researcherType,
    harness_engine: value.harnessEngine,
    prompt: value.prompt,
    skills: value.skills,
    mcp_servers: value.mcpServers,
    title: value.title,
  };
}

function optionalString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

export function adaptTaskTurn(value: TurnResponse): TaskTurn {
  return {
    status: value.status,
    task_id: value.task_id,
    turn_id: value.turn_id,
    turn_seq: value.turn_seq,
    started_at: optionalString(value.started_at),
    finished_at: optionalString(value.finished_at),
    failure_code: optionalString(value.failure_code),
    token_usage_json: optionalString(value.token_usage_json),
    context_snapshot_ref: optionalString(value.context_snapshot_ref),
  };
}

export function adaptTaskTurnItem(value: TurnItemResponse): TaskTurnItem {
  return {
    actor: value.actor,
    item_id: value.item_id,
    item_type: value.item_type,
    payload: value.payload ?? {},
    task_id: value.task_id,
    task_item_seq: value.task_item_seq,
    turn_id: value.turn_id,
    turn_item_seq: value.turn_item_seq,
    persisted_at: optionalString(value.persisted_at),
  };
}

export function adaptTask(value: TaskSummaryResponse): TaskSummary {
  return {
    ...value,
    status: value.status as TaskStatus,
    work_status: value.work_status,
    started_at: value.started_at ?? null,
    completed_at: value.completed_at ?? null,
    error_summary: value.error_summary ?? null,
    prompt: value.prompt,
  };
}

export function adaptTaskList(value: { items: TaskSummaryResponse[]; total?: number }): TaskListResponse {
  return { items: value.items.map(adaptTask), total: value.total, has_more: false, next_cursor: null };
}
