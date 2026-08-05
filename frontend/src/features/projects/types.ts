export type ProjectRecord = {
  project_id: string;
  name: string;
  description: string | null;
  default_workspace_id: string | null;
  default_environment_id: string | null;
  created_at: string;
  updated_at: string;
  owner_user_id: string | null;
};

export type ProjectUsageSummary = {
  project_id: string;
  task_count: number;
  attempt_count: number;
  total_tokens: number;
  total_cost_usd: number;
  total_duration_ms: number;
  by_model: Record<string, Record<string, unknown>>;
};
