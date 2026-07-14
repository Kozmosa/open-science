import { api } from '@/shared/api/client';
import { idempotencyHeaders } from '@/shared/api/idempotency';
import type {
  DomainCapabilities,
  DomainProjectContext,
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

export function getDomainTaskAttempts(taskId: string): Promise<ItemList<DomainTaskAttempt>> {
  return api.get(`/tasks/${encodeURIComponent(taskId)}/attempts`);
}

export function getDomainTaskContext(taskId: string): Promise<DomainTaskContextSnapshot> {
  return api.get(`/domain/tasks/${encodeURIComponent(taskId)}/context`);
}

export function getDomainProjectContext(projectId: string): Promise<DomainProjectContext> {
  return api.get(`/domain/projects/${encodeURIComponent(projectId)}/context`);
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
