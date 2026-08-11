import type {
  DomainCapabilitiesResponse,
  DomainContextCandidateResponse,
  DomainContextDiffResponse,
  DomainContextDraftResponse,
  DomainContextVersionResponse,
  DomainOverviewDisplayCardResponse,
  DomainOverviewPlannerReadinessResponse,
  DomainOverviewRefreshJobResponse,
  DomainOverviewSnapshotResponse,
  DomainOverviewSourceCardResponse,
  DomainParticipantReadinessResponse,
  DomainPrimaryWorkspaceResponse,
  DomainProjectPermissionsResponse,
  DomainProjectSummaryResponse,
  DomainTaskContextResponse,
  DomainWorkspaceEnvironmentResponse,
  DomainWorkspaceGitStatusResponse,
  DomainWorkspaceProjectLinkResponse,
  DomainWorkspaceResponse,
  ProjectMemberResponse,
} from '@/generated/transport';

export type DomainProjectRole = DomainProjectSummaryResponse['current_user_role'];

export type DomainParticipantReadiness = DomainParticipantReadinessResponse;

export type DomainOverviewPlannerReadiness = Omit<
  DomainOverviewPlannerReadinessResponse,
  'planner_id' | 'heartbeat_at' | 'last_schedule_at' | 'last_error'
> & {
  planner_id: string | null;
  heartbeat_at: string | null;
  last_schedule_at: string | null;
  last_error: string | null;
};

export type DomainCapabilities = Omit<
  DomainCapabilitiesResponse,
  'overview_snapshot_planner'
> & {
  overview_snapshot_planner: DomainOverviewPlannerReadiness;
};

export type DomainCapabilityName =
  | 'standard_task_create'
  | 'project_context'
  | 'workspace_links'
  | 'literature_research_task'
  | 'overview_snapshot';

export interface DomainCapabilityAvailability {
  available: boolean;
  reason: string | null;
}

export type DomainProjectPermissions = DomainProjectPermissionsResponse;

export type DomainPrimaryWorkspace = Omit<
  DomainPrimaryWorkspaceResponse,
  'cannot_execute_reason'
> & {
  cannot_execute_reason: string | null;
};

export type DomainProjectProjection = Omit<
  DomainProjectSummaryResponse,
  'description' | 'primary_workspace' | 'attention_reasons'
> & {
  description: string | null;
  primary_workspace: DomainPrimaryWorkspace | null;
  attention_reasons: string[];
};

export type DomainWorkspaceEnvironment = DomainWorkspaceEnvironmentResponse;

export type DomainWorkspaceProjectLink = Omit<
  DomainWorkspaceProjectLinkResponse,
  'cannot_execute_reason'
> & {
  cannot_execute_reason: string | null;
};

export type DomainWorkspaceGitStatus = Omit<
  DomainWorkspaceGitStatusResponse,
  'branch' | 'is_dirty' | 'observed_at'
> & {
  branch: string | null;
  is_dirty: boolean | null;
  observed_at: string | null;
};

export type DomainWorkspaceProjection = Omit<
  DomainWorkspaceResponse,
  | 'description'
  | 'workspace_context'
  | 'project_links'
  | 'cannot_execute_reason'
  | 'git_status'
> & {
  description: string | null;
  workspace_context: string | null;
  project_links: DomainWorkspaceProjectLink[];
  cannot_execute_reason: string | null;
  git_status: DomainWorkspaceGitStatus;
};

export type DomainContextDraft = DomainContextDraftResponse;

export type DomainContextVersion = Omit<DomainContextVersionResponse, 'assembly_eligible'> & {
  assembly_eligible: boolean;
};

export interface DomainProjectContext {
  project_id: string;
  active_version: DomainContextVersion | null;
  draft: DomainContextDraft | null;
}

export type DomainTaskContextSnapshot = Omit<
  DomainTaskContextResponse,
  'byte_budget' | 'created_at'
> & {
  byte_budget: number | null;
  created_at: string | null;
};

export type DomainContextDiff = DomainContextDiffResponse;

export type DomainContextCandidate = Pick<
  DomainContextCandidateResponse,
  | 'candidate_id'
  | 'project_id'
  | 'content'
  | 'status'
  | 'created_at'
  | 'created_by_user_id'
  | 'source_metadata'
  | 'source_task_id'
  | 'accepted_by_user_id'
  | 'accepted_at'
  | 'rejected_by_user_id'
  | 'rejected_at'
  | 'rejection_reason'
>;

export interface DomainContextCandidateAcceptance {
  candidate: DomainContextCandidate;
  draft: DomainContextDraft | null;
}

export type DomainProjectMember = ProjectMemberResponse;

export type OverviewDisplayCardId = DomainOverviewDisplayCardResponse['id'];
export type OverviewCard = DomainOverviewSourceCardResponse;
export type OverviewDisplayCard = DomainOverviewDisplayCardResponse;

export type OverviewSnapshot = Omit<
  DomainOverviewSnapshotResponse,
  | 'display_cards'
  | 'next_scheduled_at'
  | 'source'
  | 'projects_active'
  | 'tasks_by_status'
  | 'active_turns'
> & {
  display_cards: OverviewDisplayCard[];
  next_scheduled_at: string | null;
  source: 'control_plane_only';
  projects_active: number;
  tasks_by_status: Record<string, number>;
  active_turns: number;
};

export type OverviewRefreshJob = DomainOverviewRefreshJobResponse;
