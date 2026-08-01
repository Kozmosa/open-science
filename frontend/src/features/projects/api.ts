import { api } from '@/shared/api/client';
import type { ProjectUsageSummaryResponse } from '@/shared/api/transportTypes';

export const getProjectUsageSummary = (
  projectId: string,
): Promise<ProjectUsageSummaryResponse> =>
  api.get(`/domain/projects/${projectId}/usage-summary`);
