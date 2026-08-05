import { api } from '@/shared/api/client';
import type { ResourcesResponse as TransportResourcesResponse, TaskTokenUsageSummaryResponse } from '@/generated/transport';
import { adaptResources, adaptTaskTokenUsage } from './types';
import type { ResourcesResponse, TaskTokenUsageSummary } from './types';

export const getResources = (): Promise<ResourcesResponse> => api.get<TransportResourcesResponse>('/resources').then(adaptResources);

export const getTaskTokenUsageSummary = (
  params: { includeArchived?: boolean } = {},
): Promise<TaskTokenUsageSummary> => {
  const search = new URLSearchParams({ include_archived: String(params.includeArchived ?? true) });
  return api.get<TaskTokenUsageSummaryResponse>(`/tasks/token-usage?${search.toString()}`).then(adaptTaskTokenUsage);
};
