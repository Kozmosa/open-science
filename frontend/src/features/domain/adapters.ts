import type {
  DomainCapabilitiesResponse,
  DomainContextCandidateAcceptResponse,
  DomainContextCandidateListResponse,
  DomainContextCandidateResponse,
  DomainContextDraftMutationResponse,
  DomainContextDraftResponse,
  DomainContextVersionListResponse,
  DomainContextVersionResponse,
  DomainOverviewRefreshJobResponse,
  DomainOverviewSnapshotResponse,
  DomainProjectContextResponse,
  DomainProjectListResponse,
  DomainProjectSummaryResponse,
  DomainTaskContextResponse,
  DomainWorkspaceListResponse,
  DomainWorkspaceResponse,
  ProjectMemberListResponse,
  ProjectMemberResponse,
} from '@/generated/transport';
import type {
  DomainCapabilities,
  DomainContextCandidate,
  DomainContextCandidateAcceptance,
  DomainContextDraft,
  DomainContextVersion,
  DomainProjectContext,
  DomainProjectMember,
  DomainProjectProjection,
  DomainTaskContextSnapshot,
  DomainWorkspaceProjection,
  OverviewRefreshJob,
  OverviewSnapshot,
} from './types';

interface ItemList<T> {
  items: T[];
}

export function adaptDomainCapabilities(value: DomainCapabilitiesResponse): DomainCapabilities {
  return {
    ...value,
    task_dispatcher: { ...value.task_dispatcher },
    overview_snapshot_planner: {
      ...value.overview_snapshot_planner,
      planner_id: value.overview_snapshot_planner.planner_id ?? null,
      heartbeat_at: value.overview_snapshot_planner.heartbeat_at ?? null,
      last_schedule_at: value.overview_snapshot_planner.last_schedule_at ?? null,
      last_error: value.overview_snapshot_planner.last_error ?? null,
    },
  };
}

export function adaptDomainProject(
  value: DomainProjectSummaryResponse,
): DomainProjectProjection {
  return {
    ...value,
    description: value.description ?? null,
    primary_workspace: value.primary_workspace
      ? {
          ...value.primary_workspace,
          cannot_execute_reason: value.primary_workspace.cannot_execute_reason ?? null,
        }
      : null,
    attention_reasons: value.attention_reasons ?? [],
  };
}

export function adaptDomainProjectList(
  value: DomainProjectListResponse,
): ItemList<DomainProjectProjection> {
  return { items: value.items.map(adaptDomainProject) };
}

export function adaptDomainWorkspace(
  value: DomainWorkspaceResponse,
): DomainWorkspaceProjection {
  return {
    ...value,
    description: value.description ?? null,
    workspace_context: value.workspace_context ?? null,
    project_links: (value.project_links ?? []).map((link) => ({
      ...link,
      cannot_execute_reason: link.cannot_execute_reason ?? null,
    })),
    cannot_execute_reason: value.cannot_execute_reason ?? null,
    git_status: {
      ...value.git_status,
      branch: value.git_status.branch ?? null,
      is_dirty: value.git_status.is_dirty ?? null,
      observed_at: value.git_status.observed_at ?? null,
    },
  };
}

export function adaptDomainWorkspaceList(
  value: DomainWorkspaceListResponse,
): ItemList<DomainWorkspaceProjection> {
  return { items: value.items.map(adaptDomainWorkspace) };
}

export function adaptDomainContextDraft(
  value: DomainContextDraftResponse | DomainContextDraftMutationResponse,
): DomainContextDraft {
  return {
    content: value.content,
    fingerprint: value.fingerprint,
    updated_by_user_id: value.updated_by_user_id,
    updated_at: value.updated_at,
  };
}

export function adaptDomainContextVersion(
  value: DomainContextVersionResponse,
): DomainContextVersion {
  return {
    ...value,
    assembly_eligible:
      value.assembly_eligible ?? value.fragment_provenance_status === 'verified',
  };
}

export function adaptDomainContextVersionList(
  value: DomainContextVersionListResponse,
): ItemList<DomainContextVersion> {
  return { items: value.items.map(adaptDomainContextVersion) };
}

export function adaptDomainProjectContext(
  value: DomainProjectContextResponse,
): DomainProjectContext {
  return {
    project_id: value.project_id,
    active_version: value.active_version
      ? adaptDomainContextVersion(value.active_version)
      : null,
    draft: value.draft ? adaptDomainContextDraft(value.draft) : null,
  };
}

export function adaptDomainTaskContext(
  value: DomainTaskContextResponse,
): DomainTaskContextSnapshot {
  return {
    ...value,
    byte_budget: value.byte_budget ?? null,
    created_at: value.created_at ?? null,
  };
}

export function adaptDomainContextCandidate(
  value: DomainContextCandidateResponse,
): DomainContextCandidate {
  return {
    candidate_id: value.candidate_id,
    project_id: value.project_id,
    content: value.content,
    status: value.status,
    created_at: value.created_at,
    created_by_user_id: value.created_by_user_id,
    source_metadata: value.source_metadata,
    source_task_id: value.source_task_id,
    accepted_by_user_id: value.accepted_by_user_id,
    accepted_at: value.accepted_at,
    rejected_by_user_id: value.rejected_by_user_id,
    rejected_at: value.rejected_at,
    rejection_reason: value.rejection_reason,
  };
}

export function adaptDomainContextCandidateList(
  value: DomainContextCandidateListResponse,
): ItemList<DomainContextCandidate> {
  return { items: value.items.map(adaptDomainContextCandidate) };
}

export function adaptDomainContextCandidateAcceptance(
  value: DomainContextCandidateAcceptResponse,
): DomainContextCandidateAcceptance {
  return {
    candidate: adaptDomainContextCandidate(value.candidate),
    draft: value.draft ? adaptDomainContextDraft(value.draft) : null,
  };
}

export function adaptDomainProjectMember(value: ProjectMemberResponse): DomainProjectMember {
  return { ...value };
}

export function adaptDomainProjectMemberList(
  value: ProjectMemberListResponse,
): ItemList<DomainProjectMember> {
  return { items: value.items.map(adaptDomainProjectMember) };
}

export function adaptOverviewSnapshot(
  value: DomainOverviewSnapshotResponse,
): OverviewSnapshot {
  return {
    ...value,
    cards: value.cards.map((card) => ({ ...card })),
    display_cards: (value.display_cards ?? []).map((card) => ({ ...card })),
    next_scheduled_at: value.next_scheduled_at ?? null,
    source: value.source ?? 'control_plane_only',
    projects_active: value.projects_active ?? 0,
    tasks_by_status: value.tasks_by_status ?? {},
    active_turns: value.active_turns ?? 0,
  };
}

export function adaptOverviewRefreshJob(
  value: DomainOverviewRefreshJobResponse,
): OverviewRefreshJob {
  return { ...value };
}
