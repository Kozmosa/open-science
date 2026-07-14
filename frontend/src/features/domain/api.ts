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
  DomainTaskAttempt,
  DomainTaskContextSnapshot,
  DomainWorkspaceProjection,
  OverviewRefreshJob,
  OverviewSnapshot,
} from './types';

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

export function getDomainTaskAttempts(taskId: string): Promise<ItemList<DomainTaskAttempt>> {
  return api.get(`/tasks/${encodeURIComponent(taskId)}/attempts`);
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
    `/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}?allow_no_primary=${allowNoPrimary}`,
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
    `/projects/${encodeURIComponent(projectId)}/primary-workspace/${encodeURIComponent(workspaceId)}?previous_workspace_id=${encodeURIComponent(previousWorkspaceId)}`,
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
  return api.get(`/projects/${encodeURIComponent(projectId)}/members`);
}

export function upsertDomainProjectMember(projectId: string, userId: string, role: 'viewer' | 'editor', canPublish: boolean, idempotencyKey: string): Promise<DomainProjectMember> {
  return api.put(`/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { role, can_publish: canPublish }, { headers: idempotencyHeaders(idempotencyKey) });
}

export function removeDomainProjectMember(projectId: string, userId: string, idempotencyKey: string): Promise<void> {
  return api.delete(`/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { headers: idempotencyHeaders(idempotencyKey) });
}

export function archiveDomainProject(projectId: string, idempotencyKey: string): Promise<void> {
  return domainPost(`/projects/${encodeURIComponent(projectId)}/archive`, {}, idempotencyKey);
}

export function unarchiveDomainProject(projectId: string, idempotencyKey: string): Promise<void> {
  return domainPost(`/projects/${encodeURIComponent(projectId)}/unarchive`, {}, idempotencyKey);
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
