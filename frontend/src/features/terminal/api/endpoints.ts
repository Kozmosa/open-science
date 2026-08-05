import { api } from '@/shared/api/client';
import type { TerminalSessionResponse, UserSessionPairListResponse as TransportUserSessionPairListResponse } from '@/generated/transport';
import { adaptSessionPairs, adaptTerminalSession } from '../types';
import type { TerminalSession, UserSessionPairListResponse } from '../types';

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
  api.get<TerminalSessionResponse>(withEnvironmentId('/terminal/session', environmentId)).then(adaptTerminalSession);

export const getSessionPairs = (environmentId?: string): Promise<UserSessionPairListResponse> =>
  api.get<TransportUserSessionPairListResponse>(withEnvironmentId('/terminal/session-pairs', environmentId)).then(adaptSessionPairs);

export const createTerminalSession = (environmentId: string): Promise<TerminalSession> =>
  api.post<TerminalSessionResponse>('/terminal/session', { environment_id: environmentId }).then(adaptTerminalSession);

export const deleteTerminalSession = (options: {
  environmentId?: string | null;
  attachmentId?: string | null;
}): Promise<TerminalSession> => api.delete<TerminalSessionResponse>(withDetachQuery('/terminal/session', options)).then(adaptTerminalSession);

export const resetTerminalSession = (
  environmentId: string,
  attachmentId?: string | null,
): Promise<TerminalSession> => api.post<TerminalSessionResponse>('/terminal/session/reset', {
  environment_id: environmentId,
  attachment_id: attachmentId ?? null,
}).then(adaptTerminalSession);
