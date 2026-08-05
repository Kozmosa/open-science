import { api } from '@/shared/api/client';
import type { ProjectUsageSummaryResponse } from '@/generated/transport';
import type { ProjectUsageSummary } from './types';

export const getProjectUsageSummary = (
  projectId: string,
): Promise<ProjectUsageSummary> =>
  api.get<ProjectUsageSummaryResponse>(`/domain/projects/${projectId}/usage-summary`).then((value) => ({
    project_id: value.project_id,
    task_count: value.task_count,
    attempt_count: value.attempt_count,
    total_tokens: value.total_tokens,
    total_cost_usd: value.total_cost_usd,
    total_duration_ms: value.total_duration_ms,
    by_model: value.by_model ?? {},
  }));
