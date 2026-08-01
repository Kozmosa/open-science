import { api } from '@/shared/api/client';
import type { TerminalSession, UserSessionPairListResponse } from '@/shared/types';

function withEnvironmentId(path: string, environmentId?: string): string {
  if (!environmentId) return path;
  return `${path}?${new URLSearchParams({ environment_id: environmentId }).toString()}`;
}

function withDetachQuery(
  path: string,
  options: { environmentId?: string | null; attachmentId?: string | null },
): string {
  const search = new URLSearchParams();
  if (options.environmentId) search.set('environment_id', options.environmentId);
  if (options.attachmentId) search.set('attachment_id', options.attachmentId);
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export const getTerminalSession = (environmentId?: string): Promise<TerminalSession> =>
  api.get(withEnvironmentId('/terminal/session', environmentId));

export const getSessionPairs = (environmentId?: string): Promise<UserSessionPairListResponse> =>
  api.get(withEnvironmentId('/terminal/session-pairs', environmentId));

export const createTerminalSession = (environmentId: string): Promise<TerminalSession> =>
  api.post('/terminal/session', { environment_id: environmentId });

export const deleteTerminalSession = (options: {
  environmentId?: string | null;
  attachmentId?: string | null;
}): Promise<TerminalSession> => api.delete(withDetachQuery('/terminal/session', options));

export const resetTerminalSession = (
  environmentId: string,
  attachmentId?: string | null,
): Promise<TerminalSession> => api.post('/terminal/session/reset', {
  environment_id: environmentId,
  attachment_id: attachmentId ?? null,
});
