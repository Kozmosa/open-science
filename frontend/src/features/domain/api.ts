import { api } from '@/shared/api/client';
import { idempotencyHeaders } from '@/shared/api/idempotency';
import type {
  DomainCapabilities,
  DomainContextCandidate,
  DomainContextDiff,
  DomainContextVersion,
  DomainProjectContext,
  DomainProjectMember,
  DomainProjectProjection,
  DomainTaskContextSnapshot,
  DomainWorkspaceProjection,
  OverviewRefreshJob,
  OverviewSnapshot,
} from './types';
import type {
  EnvironmentListResponse,
  EnvironmentRecord,
  ProjectEnvironmentReferenceListResponse,
} from '@/shared/types';
import type {
  EnvironmentCreateRequest,
  EnvironmentUpdateRequest,
  ProjectUpdateRequest,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceUpdateRequest,
  WorkspaceUpdateRequest,
} from '@/shared/api/transportTypes';

interface ItemList<T> {
  items: T[];
}

export function getDomainCapabilities(): Promise<DomainCapabilities> {
  return api.get('/domain/capabilities');
}

export function getDomainProjects(includeArchived = false): Promise<ItemList<DomainProjectProjection>> {
  return api.get(`/domain/projects?include_archived=${includeArchived}`);
}

export function getDomainProject(projectId: string): Promise<DomainProjectProjection> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}`);
}

export function getDomainWorkspaces(
  includeUnregistered = false,
): Promise<ItemList<DomainWorkspaceProjection>> {
  return api.get(`/domain/workspaces?include_unregistered=${includeUnregistered}`);
}

export function getDomainWorkspace(workspaceId: string): Promise<DomainWorkspaceProjection> {
  return api.get(`/domain/workspaces/${encodeURIComponent(workspaceId)}`);
}

export function createDomainWorkspace(
  payload: { environment_id: string; canonical_path: string; label: string },
  idempotencyKey: string,
): Promise<{ workspace_id: string }> {
  return domainPost('/domain/workspaces', payload, idempotencyKey);
}

export function attachDomainWorkspace(
  projectId: string,
  workspaceId: string,
  idempotencyKey: string,
): Promise<Record<string, unknown>> {
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
): Promise<Record<string, unknown>> {
  return api.put(
    `/domain/projects/${encodeURIComponent(projectId)}/primary-workspace/${encodeURIComponent(workspaceId)}`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function getDomainTaskContext(taskId: string): Promise<DomainTaskContextSnapshot> {
  return api.get(`/domain/tasks/${encodeURIComponent(taskId)}/context`);
}

export function getDomainProjectContext(projectId: string): Promise<DomainProjectContext> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/context`);
}

export function createDomainProject(
  payload: { name: string; description: string | null },
  idempotencyKey: string,
): Promise<{ project_id: string }> {
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
): Promise<Record<string, unknown>> {
  return api.put(
    `/domain/projects/${encodeURIComponent(projectId)}/primary-workspace/${encodeURIComponent(workspaceId)}?previous_workspace_id=${encodeURIComponent(previousWorkspaceId)}`,
    {},
    { headers: idempotencyHeaders(idempotencyKey) },
  );
}

export function saveDomainProjectContextDraft(projectId: string, content: string, idempotencyKey: string): Promise<DomainProjectContext> {
  return api.put(`/domain/projects/${encodeURIComponent(projectId)}/context/draft`, { content }, { headers: idempotencyHeaders(idempotencyKey) });
}

export function publishDomainProjectContext(projectId: string, idempotencyKey: string): Promise<DomainContextVersion> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/context/publish`, {}, idempotencyKey);
}

export function getDomainProjectContextVersions(projectId: string): Promise<ItemList<DomainContextVersion>> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/context/versions`);
}

export function getDomainProjectContextDiff(projectId: string, contextVersionId: string, against: string): Promise<DomainContextDiff> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/context/versions/${encodeURIComponent(contextVersionId)}/diff?against=${encodeURIComponent(against)}`);
}

export function getDomainProjectContextCandidates(projectId: string): Promise<ItemList<DomainContextCandidate>> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/context/candidates`);
}

export function acceptDomainContextCandidate(projectId: string, candidateId: string, idempotencyKey: string): Promise<DomainContextCandidate> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/context/candidates/${encodeURIComponent(candidateId)}/accept`, {}, idempotencyKey);
}

export function rejectDomainContextCandidate(projectId: string, candidateId: string, reason: string, idempotencyKey: string): Promise<DomainContextCandidate> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/context/candidates/${encodeURIComponent(candidateId)}/reject`, { reason }, idempotencyKey);
}

export function getDomainProjectMembers(projectId: string): Promise<ItemList<DomainProjectMember>> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/members`);
}

export function upsertDomainProjectMember(projectId: string, userId: string, role: 'viewer' | 'editor', canPublish: boolean, idempotencyKey: string): Promise<DomainProjectMember> {
  return api.put(`/domain/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { role, can_publish: canPublish }, { headers: idempotencyHeaders(idempotencyKey) });
}

export function removeDomainProjectMember(projectId: string, userId: string, idempotencyKey: string): Promise<void> {
  return api.delete(`/domain/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { headers: idempotencyHeaders(idempotencyKey) });
}

export function archiveDomainProject(projectId: string, idempotencyKey: string): Promise<void> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/archive`, {}, idempotencyKey);
}

export function unarchiveDomainProject(projectId: string, idempotencyKey: string): Promise<void> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/unarchive`, {}, idempotencyKey);
}

export function updateDomainProject(
  projectId: string,
  payload: ProjectUpdateRequest,
  idempotencyKey: string,
): Promise<DomainProjectProjection> {
  return domainPatch(`/domain/projects/${encodeURIComponent(projectId)}`, payload, idempotencyKey);
}

export function updateDomainWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdateRequest,
  idempotencyKey: string,
): Promise<DomainWorkspaceProjection> {
  return domainPatch(`/domain/workspaces/${encodeURIComponent(workspaceId)}`, payload, idempotencyKey);
}

export function unregisterDomainWorkspace(
  workspaceId: string,
  idempotencyKey: string,
): Promise<void> {
  return domainPost(`/domain/workspaces/${encodeURIComponent(workspaceId)}/unregister`, {}, idempotencyKey);
}

export function getDomainEnvironments(): Promise<EnvironmentListResponse> {
  return api.get('/domain/environments');
}

export function getDomainEnvironment(environmentId: string): Promise<EnvironmentRecord> {
  return api.get(`/domain/environments/${encodeURIComponent(environmentId)}`);
}

export function createDomainEnvironment(
  payload: EnvironmentCreateRequest,
  idempotencyKey: string,
): Promise<EnvironmentRecord> {
  return domainPost('/domain/environments', payload, idempotencyKey);
}

export function updateDomainEnvironment(
  environmentId: string,
  payload: EnvironmentUpdateRequest,
  idempotencyKey: string,
): Promise<EnvironmentRecord> {
  return domainPatch(`/domain/environments/${encodeURIComponent(environmentId)}`, payload, idempotencyKey);
}

export function disableDomainEnvironment(
  environmentId: string,
  idempotencyKey: string,
): Promise<void> {
  return domainDelete(`/domain/environments/${encodeURIComponent(environmentId)}`, idempotencyKey);
}

export function detectDomainEnvironment(environmentId: string): Promise<EnvironmentRecord> {
  return api.post(`/domain/environments/${encodeURIComponent(environmentId)}/detect`, {});
}

export function getDomainProjectEnvironmentReferences(
  projectId: string,
): Promise<ProjectEnvironmentReferenceListResponse> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/environment-refs`);
}

export function createDomainProjectEnvironmentReference(
  projectId: string,
  payload: ProjectEnvironmentReferenceCreateRequest,
  idempotencyKey: string,
): Promise<import('@/shared/types').ProjectEnvironmentReference> {
  return domainPost(`/domain/projects/${encodeURIComponent(projectId)}/environment-refs`, payload, idempotencyKey);
}

export function updateDomainProjectEnvironmentReference(
  projectId: string,
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest,
  idempotencyKey: string,
): Promise<import('@/shared/types').ProjectEnvironmentReference> {
  return domainPatch(`/domain/projects/${encodeURIComponent(projectId)}/environment-refs/${encodeURIComponent(environmentId)}`, payload, idempotencyKey);
}

export function deleteDomainProjectEnvironmentReference(
  projectId: string,
  environmentId: string,
  idempotencyKey: string,
): Promise<void> {
  return domainDelete(`/domain/projects/${encodeURIComponent(projectId)}/environment-refs/${encodeURIComponent(environmentId)}`, idempotencyKey);
}

export function getTodayOverview(): Promise<OverviewSnapshot> {
  return api.get('/domain/overview/today');
}

export function requestTodayOverviewRefresh(idempotencyKey: string): Promise<OverviewRefreshJob> {
  return api.post('/domain/overview/today/refresh', {}, {
    headers: idempotencyHeaders(idempotencyKey),
  });
}

export function getOverviewRefreshJob(jobId: string): Promise<OverviewRefreshJob> {
  return api.get(`/domain/overview/refresh/${encodeURIComponent(jobId)}`);
}

export function domainPost<TResponse>(
  path: string,
  body: unknown,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.post(path, body, { headers: idempotencyHeaders(idempotencyKey) });
}

export function domainPut<TResponse>(
  path: string,
  body: unknown,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.put(path, body, { headers: idempotencyHeaders(idempotencyKey) });
}

export function domainPatch<TResponse>(
  path: string,
  body: unknown,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.patch(path, body, { headers: idempotencyHeaders(idempotencyKey) });
}

export function domainDelete<TResponse>(
  path: string,
  idempotencyKey: string,
): Promise<TResponse> {
  return api.delete(path, { headers: idempotencyHeaders(idempotencyKey) });
}
