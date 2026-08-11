import type {
  DomainCapabilitiesResponse,
  DomainContextCandidateAcceptResponse,
  DomainContextCandidateListResponse,
  DomainContextCandidateResponse,
  DomainContextDiffResponse,
  DomainContextDraftMutationResponse,
  DomainContextVersionListResponse,
  DomainContextVersionResponse,
  DomainOverviewRefreshJobResponse,
  DomainOverviewSnapshotResponse,
  DomainProjectContextResponse,
  DomainProjectCreateRequest,
  DomainProjectCreateResponse,
  DomainProjectListResponse,
  DomainProjectSummaryResponse,
  DomainTaskContextResponse,
  DomainWorkspaceCreateRequest,
  DomainWorkspaceCreateResponse,
  DomainWorkspaceLinkResponse,
  DomainWorkspaceListResponse,
  DomainWorkspaceResponse,
  ProjectContextCandidateRejectRequest,
  ProjectContextDraftRequest,
  ProjectMemberListResponse,
  ProjectMemberRequest,
  ProjectMemberResponse,
  ProjectUpdateRequest,
  WorkspaceUpdateRequest,
} from '@/generated/transport';
import { api } from '@/shared/api/client';
import { idempotencyHeaders } from '@/shared/api/idempotency';
import {
  adaptDomainCapabilities,
  adaptDomainContextCandidate,
  adaptDomainContextCandidateAcceptance,
  adaptDomainContextCandidateList,
  adaptDomainContextDraft,
  adaptDomainContextVersion,
  adaptDomainContextVersionList,
  adaptDomainProject,
  adaptDomainProjectContext,
  adaptDomainProjectList,
  adaptDomainProjectMember,
  adaptDomainProjectMemberList,
  adaptDomainTaskContext,
  adaptDomainWorkspace,
  adaptDomainWorkspaceList,
  adaptOverviewRefreshJob,
  adaptOverviewSnapshot,
} from './adapters';
import type {
  DomainCapabilities,
  DomainContextCandidate,
  DomainContextCandidateAcceptance,
  DomainContextDiff,
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

export function getDomainCapabilities(): Promise<DomainCapabilities> {
  return api
    .get<DomainCapabilitiesResponse>('/domain/capabilities')
    .then(adaptDomainCapabilities);
}

export function getDomainProjects(
  includeArchived = false,
): Promise<ItemList<DomainProjectProjection>> {
  return api
    .get<DomainProjectListResponse>(`/domain/projects?include_archived=${includeArchived}`)
    .then(adaptDomainProjectList);
}

export function getDomainProject(projectId: string): Promise<DomainProjectProjection> {
  return api
    .get<DomainProjectSummaryResponse>(`/domain/projects/${encodeURIComponent(projectId)}`)
    .then(adaptDomainProject);
}

export function getDomainWorkspaces(
  includeUnregistered = false,
): Promise<ItemList<DomainWorkspaceProjection>> {
  return api
    .get<DomainWorkspaceListResponse>(
      `/domain/workspaces?include_unregistered=${includeUnregistered}`,
    )
    .then(adaptDomainWorkspaceList);
}

export function getDomainWorkspace(workspaceId: string): Promise<DomainWorkspaceProjection> {
  return api
    .get<DomainWorkspaceResponse>(`/domain/workspaces/${encodeURIComponent(workspaceId)}`)
    .then(adaptDomainWorkspace);
}

export function createDomainWorkspace(
  payload: DomainWorkspaceCreateRequest,
  idempotencyKey: string,
): Promise<DomainWorkspaceCreateResponse> {
  return domainPost('/domain/workspaces', payload, idempotencyKey);
}

export function attachDomainWorkspace(
  projectId: string,
  workspaceId: string,
  idempotencyKey: string,
): Promise<DomainWorkspaceLinkResponse> {
  return domainPost(
    `/domain/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}`,
    {},
    idempotencyKey,
  );
}

export function setDomainPrimaryWorkspace(
  projectId: string,
  workspaceId: string,
  idempotencyKey: string,
): Promise<DomainWorkspaceLinkResponse> {
  return api.put(
    `/domain/projects/${encodeURIComponent(projectId)}/primary-workspace/${encodeURIComponent(workspaceId)}`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function getDomainTaskContext(taskId: string): Promise<DomainTaskContextSnapshot> {
  return api
    .get<DomainTaskContextResponse>(`/domain/tasks/${encodeURIComponent(taskId)}/context`)
    .then(adaptDomainTaskContext);
}

export function getDomainProjectContext(projectId: string): Promise<DomainProjectContext> {
  return api
    .get<DomainProjectContextResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/context`,
    )
    .then(adaptDomainProjectContext);
}

export function createDomainProject(
  payload: DomainProjectCreateRequest,
  idempotencyKey: string,
): Promise<DomainProjectCreateResponse> {
  return domainPost('/domain/projects', payload, idempotencyKey);
}

export function detachDomainWorkspace(
  projectId: string,
  workspaceId: string,
  idempotencyKey: string,
  allowNoPrimary = false,
): Promise<void> {
  return api.delete(
    `/domain/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}?allow_no_primary=${allowNoPrimary}`,
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function replaceDomainPrimaryWorkspace(
  projectId: string,
  previousWorkspaceId: string,
  workspaceId: string,
  idempotencyKey: string,
): Promise<DomainWorkspaceLinkResponse> {
  return api.put(
    `/domain/projects/${encodeURIComponent(projectId)}/primary-workspace/${encodeURIComponent(workspaceId)}?previous_workspace_id=${encodeURIComponent(previousWorkspaceId)}`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function saveDomainProjectContextDraft(
  projectId: string,
  content: string,
  idempotencyKey: string,
): Promise<DomainContextDraft> {
  const payload: ProjectContextDraftRequest = { content };
  return api
    .put<DomainContextDraftMutationResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/context/draft`,
      payload,
      { headers: idempotencyHeaders(idempotencyKey) },
    )
    .then(adaptDomainContextDraft);
}

export function publishDomainProjectContext(
  projectId: string,
  idempotencyKey: string,
): Promise<DomainContextVersion> {
  return domainPost<DomainContextVersionResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/context/publish`,
    {},
    idempotencyKey,
  ).then(adaptDomainContextVersion);
}

export function getDomainProjectContextVersions(
  projectId: string,
): Promise<ItemList<DomainContextVersion>> {
  return api
    .get<DomainContextVersionListResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/context/versions`,
    )
    .then(adaptDomainContextVersionList);
}

export function getDomainProjectContextDiff(
  projectId: string,
  contextVersionId: string,
  against: string,
): Promise<DomainContextDiff> {
  return api.get<DomainContextDiffResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/context/versions/${encodeURIComponent(contextVersionId)}/diff?against=${encodeURIComponent(against)}`,
  );
}

export function getDomainProjectContextCandidates(
  projectId: string,
): Promise<ItemList<DomainContextCandidate>> {
  return api
    .get<DomainContextCandidateListResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/context/candidates`,
    )
    .then(adaptDomainContextCandidateList);
}

export function acceptDomainContextCandidate(
  projectId: string,
  candidateId: string,
  idempotencyKey: string,
): Promise<DomainContextCandidateAcceptance> {
  return domainPost<DomainContextCandidateAcceptResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/context/candidates/${encodeURIComponent(candidateId)}/accept`,
    {},
    idempotencyKey,
  ).then(adaptDomainContextCandidateAcceptance);
}

export function rejectDomainContextCandidate(
  projectId: string,
  candidateId: string,
  reason: string,
  idempotencyKey: string,
): Promise<DomainContextCandidate> {
  const payload: ProjectContextCandidateRejectRequest = { reason };
  return domainPost<DomainContextCandidateResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/context/candidates/${encodeURIComponent(candidateId)}/reject`,
    payload,
    idempotencyKey,
  ).then(adaptDomainContextCandidate);
}

export function getDomainProjectMembers(
  projectId: string,
): Promise<ItemList<DomainProjectMember>> {
  return api
    .get<ProjectMemberListResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/members`,
    )
    .then(adaptDomainProjectMemberList);
}

export function upsertDomainProjectMember(
  projectId: string,
  userId: string,
  role: DomainProjectMember['role'],
  canPublish: boolean,
  idempotencyKey: string,
): Promise<DomainProjectMember> {
  const payload: ProjectMemberRequest = { role, can_publish: canPublish };
  return api
    .put<ProjectMemberResponse>(
      `/domain/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
      payload,
      { headers: idempotencyHeaders(idempotencyKey) },
    )
    .then(adaptDomainProjectMember);
}

export function removeDomainProjectMember(
  projectId: string,
  userId: string,
  idempotencyKey: string,
): Promise<void> {
  return api.delete(
    `/domain/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function archiveDomainProject(projectId: string, idempotencyKey: string): Promise<void> {
  return domainPost(
    `/domain/projects/${encodeURIComponent(projectId)}/archive`,
    {},
    idempotencyKey,
  );
}

export function unarchiveDomainProject(
  projectId: string,
  idempotencyKey: string,
): Promise<void> {
  return domainPost(
    `/domain/projects/${encodeURIComponent(projectId)}/unarchive`,
    {},
    idempotencyKey,
  );
}

export function updateDomainProject(
  projectId: string,
  payload: ProjectUpdateRequest,
  idempotencyKey: string,
): Promise<DomainProjectProjection> {
  return domainPatch<DomainProjectSummaryResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}`,
    payload,
    idempotencyKey,
  ).then(adaptDomainProject);
}

export function updateDomainWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdateRequest,
  idempotencyKey: string,
): Promise<DomainWorkspaceProjection> {
  return domainPatch<DomainWorkspaceResponse>(
    `/domain/workspaces/${encodeURIComponent(workspaceId)}`,
    payload,
    idempotencyKey,
  ).then(adaptDomainWorkspace);
}

export function unregisterDomainWorkspace(
  workspaceId: string,
  idempotencyKey: string,
): Promise<void> {
  return domainPost(
    `/domain/workspaces/${encodeURIComponent(workspaceId)}/unregister`,
    {},
    idempotencyKey,
  );
}

export function getTodayOverview(): Promise<OverviewSnapshot> {
  return api
    .get<DomainOverviewSnapshotResponse>('/domain/overview/today')
    .then(adaptOverviewSnapshot);
}

export function requestTodayOverviewRefresh(
  idempotencyKey: string,
): Promise<OverviewRefreshJob> {
  return api
    .post<DomainOverviewRefreshJobResponse>('/domain/overview/today/refresh', {}, {
      headers: idempotencyHeaders(idempotencyKey),
    })
    .then(adaptOverviewRefreshJob);
}

export function getOverviewRefreshJob(jobId: string): Promise<OverviewRefreshJob> {
  return api
    .get<DomainOverviewRefreshJobResponse>(
      `/domain/overview/refresh/${encodeURIComponent(jobId)}`,
    )
    .then(adaptOverviewRefreshJob);
}

function domainPost<TResponse = void>(
  path: string,
  body: unknown,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.post(path, body, { headers: idempotencyHeaders(idempotencyKey) });
}

function domainPatch<TResponse>(
  path: string,
  body: unknown,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.patch(path, body, { headers: idempotencyHeaders(idempotencyKey) });
}
