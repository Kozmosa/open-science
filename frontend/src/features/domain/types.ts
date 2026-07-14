export type DomainProjectRole = 'admin' | 'owner' | 'editor' | 'viewer';

export interface DomainParticipantReadiness {
  participant_type: string;
  ready: boolean;
  maintenance_active: boolean;
  maintenance_epoch: number | null;
  stale_after_seconds: number;
  registered_participant_ids: string[];
  active_participant_ids: string[];
  fresh_participant_ids: string[];
  stale_participant_ids: string[];
}

export interface DomainOverviewPlannerReadiness {
  job_store_ready: boolean;
  planner_ready: boolean;
  planner_status: string;
  [key: string]: unknown;
}

export interface DomainCapabilities {
  domain_contract_version: number;
  mode: string;
  standard_task_create: boolean;
  project_context: boolean;
  workspace_links: boolean;
  task_attempts: boolean;
  task_dispatcher: DomainParticipantReadiness;
  literature_research_task: boolean;
  overview_snapshot: boolean;
  overview_snapshot_job_store: boolean;
  overview_snapshot_planner: DomainOverviewPlannerReadiness;
}

export type DomainCapabilityName =
  | 'standard_task_create'
  | 'project_context'
  | 'workspace_links'
  | 'task_attempts'
  | 'literature_research_task'
  | 'overview_snapshot';

export interface DomainCapabilityAvailability {
  available: boolean;
  reason: string | null;
}

export interface DomainProjectPermissions {
  can_edit: boolean;
  can_publish: boolean;
  can_manage_members: boolean;
  can_archive: boolean;
  can_unarchive: boolean;
  can_create_task: boolean;
}

export interface DomainPrimaryWorkspace {
  workspace_id: string;
  label: string;
  canonical_path: string;
  environment_id: string;
  environment_alias: string;
  environment_display_name: string;
  is_primary: true;
  can_execute: boolean;
  cannot_execute_reason: string | null;
}

export interface DomainProjectProjection {
  project_id: string;
  name: string;
  description: string | null;
  status: 'active' | 'archived';
  is_default: boolean;
  owner_user_id: string;
  current_user_role: DomainProjectRole;
  created_at: string;
  updated_at: string;
  recent_activity_at: string;
  workspace_count: number;
  executable_workspace_count: number;
  task_count: number;
  active_task_count: number;
  running_task_count: number;
  primary_workspace: DomainPrimaryWorkspace | null;
  attention_required: boolean;
  attention_reasons: string[];
  permissions: DomainProjectPermissions;
}

export interface DomainWorkspaceEnvironment {
  environment_id: string;
  alias: string;
  display_name: string;
  status: 'active' | 'disabled';
}

export interface DomainWorkspaceProjectLink {
  project_id: string;
  project_name: string;
  project_status: 'active' | 'archived';
  current_user_role: DomainProjectRole;
  link_status: 'active' | 'retired';
  is_primary: boolean;
  can_execute: boolean;
  cannot_execute_reason: string | null;
}

export interface DomainWorkspaceGitStatus {
  state: 'not_collected' | 'available' | 'unavailable';
  branch: string | null;
  is_dirty: boolean | null;
  observed_at: string | null;
}

export interface DomainWorkspaceProjection {
  workspace_id: string;
  label: string;
  description: string | null;
  canonical_path: string;
  workspace_context: string | null;
  status: 'active' | 'unregistered';
  owner_user_id: string;
  created_at: string;
  updated_at: string;
  recent_activity_at: string;
  environment: DomainWorkspaceEnvironment;
  project_links: DomainWorkspaceProjectLink[];
  task_count: number;
  active_task_count: number;
  can_execute: boolean;
  cannot_execute_reason: string | null;
  can_manage_registry: boolean;
  git_status: DomainWorkspaceGitStatus;
}

export interface DomainTaskProjection {
  task_id: string;
  project_id: string;
  workspace_id: string;
  environment_id: string;
  title: string;
  prompt: string;
  status: string;
  owner_user_id: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  archived_at: string | null;
  archive_reason: string | null;
  project_context_version_id: string | null;
  latest_output_seq: number;
  exit_code: number | null;
  error_summary: string | null;
  researcher_type?: string;
  harness_engine?: string;
}

export interface DomainRuntimeSessionSummary {
  runtime_session_id: string;
  attempt_id: string;
  status: string;
  engine_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  [key: string]: unknown;
}

export interface DomainTaskAttempt {
  attempt_id: string;
  task_id: string;
  attempt_seq: number;
  trigger: 'initial' | 'retry' | 'resume' | 'continue' | 'legacy' | string;
  status: string;
  context_snapshot_id: string | null;
  context_version_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  token_usage_json: string | null;
  cost_usd: number | null;
  failure_reason: string | null;
  stop_reason: string | null;
  runtime_sessions: DomainRuntimeSessionSummary[];
  dispatch?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface DomainTaskRelationship {
  edge_id: string;
  project_id: string;
  source_task_id: string;
  target_task_id: string;
  relationship_type: 'derived_from' | 'depends_on' | 'related_to' | string;
  created_at: string;
}

export interface DomainContextDraft {
  content: string;
  fingerprint: string;
  updated_by_user_id: string;
  updated_at: string;
}

export interface DomainContextVersion {
  context_version_id: string;
  project_id: string;
  content: string;
  fingerprint: string;
  fragment_manifest: unknown[];
  fragment_provenance_status: string;
  fragment_provenance_evidence: Record<string, unknown>;
  assembly_eligible: boolean;
  is_active: boolean;
  created_by_user_id: string;
  created_at: string;
}

export interface DomainProjectContext {
  project_id: string;
  active_version: DomainContextVersion | null;
  draft: DomainContextDraft | null;
}

export interface DomainTaskContextSnapshot {
  context_snapshot_id: string | null;
  context_version_id: string | null;
  fingerprint: string | null;
  content: string;
  source_manifest: unknown[];
  byte_budget: number | null;
  truncated: boolean;
  created_at?: string;
}

export interface DomainContextDiff {
  project_id: string;
  before_context_version_id: string;
  after_context_version_id: string;
  diff: string;
}

export interface DomainContextCandidate {
  candidate_id: string;
  project_id: string;
  content: string;
  status: 'pending' | 'accepted' | 'rejected' | string;
  created_at: string;
  created_by_user_id: string | null;
  source_metadata: Record<string, unknown>;
  source_task_id: string | null;
  source_attempt_id: string | null;
  accepted_by_user_id: string | null;
  accepted_at: string | null;
  rejected_by_user_id: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
}

export interface DomainProjectMember {
  user_id: string;
  username: string;
  display_name: string;
  role: 'viewer' | 'editor';
  can_publish: boolean;
}

export interface LiteratureTaskIntent {
  intent_id: string;
  paper_id: string;
  project_id: string;
  workspace_id: string | null;
  task_id: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  idempotency_key: string;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}

export type OverviewDisplayCardId =
  | 'attention'
  | 'progress'
  | 'literature'
  | 'continue'
  | 'resources';

export interface OverviewCard<TData = Record<string, unknown> | null> {
  id: string;
  data: TData;
  data_cutoff_at: string;
  source_status: 'ok' | 'stale' | 'partial' | 'failed' | string;
  attention_required: boolean;
  error_summary: string | null;
}

export interface OverviewDisplayCard<TData = Record<string, unknown> | null>
  extends OverviewCard<TData> {
  id: OverviewDisplayCardId;
}

export interface OverviewSnapshot {
  snapshot_id: string;
  owner_user_id: string;
  snapshot_date: string;
  data_cutoff_at: string;
  source_status: string;
  attention_required: boolean;
  cards: OverviewCard[];
  display_cards?: OverviewDisplayCard[];
  next_scheduled_at?: string;
}

export interface OverviewRefreshJob {
  job_id: string;
  owner_user_id: string;
  trigger: string;
  scheduled_for_date: string | null;
  status: 'queued' | 'retry_wait' | 'running' | 'completed' | 'failed' | string;
  attempt_count: number;
  retry_count: number;
  next_retry_at: string | null;
  last_failure_at: string | null;
  snapshot_id: string | null;
  source_status: string | null;
  error_summary: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
}
