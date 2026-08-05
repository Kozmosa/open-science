import type {
  GpuInfo as TransportGpuInfo,
  MemoryInfo as TransportMemoryInfo,
  ProcessInfo as TransportProcessInfo,
  ResourceSnapshot as TransportResourceSnapshot,
  ResourcesResponse as TransportResourcesResponse,
  TaskTokenUsageSummaryResponse,
} from '@/generated/transport';

export type GpuInfo = TransportGpuInfo;
export type CpuInfo = { percent: number; core_count: number };
export type MemoryInfo = TransportMemoryInfo;
export type ProcessInfo = TransportProcessInfo;

export type ResourceSnapshot = {
  environment_id: string;
  environment_name: string;
  timestamp: string;
  status: 'ok' | 'degraded' | 'unavailable';
  gpus: GpuInfo[];
  cpu: CpuInfo;
  memory: MemoryInfo;
  ainrf_processes: ProcessInfo[];
};

export type ResourcesResponse = { items: ResourceSnapshot[] };
export type TaskTokenUsage = { input_tokens: number; output_tokens: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number; cost_usd?: number };
export type TaskUsageTopTask = { task_id: string; title: string; status: string; harness_engine: string; total_tokens: number; cost_usd: number; duration_ms: number | null };
export type TaskTokenUsageSummary = {
  task_count: number;
  tasks_with_usage: number;
  total_tokens: number;
  total_cost_usd: number;
  total_duration_ms: number;
  median_duration_ms: number | null;
  total: TaskTokenUsage;
  by_model: Record<string, TaskTokenUsage & { tokens?: number }>;
  by_engine: Record<string, { task_count: number; tasks_with_usage: number; tokens: number; cost_usd: number }>;
  top_tasks: TaskUsageTopTask[];
};

export function adaptResources(value: TransportResourcesResponse): ResourcesResponse {
  return {
    items: (value.items ?? []).map((item: TransportResourceSnapshot) => ({
      environment_id: item.environment_id,
      environment_name: item.environment_name,
      timestamp: item.timestamp,
      status: item.status ?? 'unavailable',
      gpus: item.gpus ?? [],
      cpu: { percent: item.cpu.percent, core_count: item.cpu.core_count ?? 0 },
      memory: item.memory,
      ainrf_processes: item.ainrf_processes ?? [],
    })),
  };
}

export function adaptTaskTokenUsage(value: TaskTokenUsageSummaryResponse): TaskTokenUsageSummary {
  const numeric = (input: unknown, fallback = 0): number => typeof input === 'number' ? input : fallback;
  const total = value.total as Record<string, unknown>;
  return {
    task_count: value.task_count,
    tasks_with_usage: value.tasks_with_usage,
    total_tokens: value.total_tokens,
    total_cost_usd: value.total_cost_usd,
    total_duration_ms: value.total_duration_ms,
    median_duration_ms: value.median_duration_ms ?? null,
    total: {
      input_tokens: numeric(total.input_tokens),
      output_tokens: numeric(total.output_tokens),
      cache_creation_input_tokens: numeric(total.cache_creation_input_tokens),
      cache_read_input_tokens: numeric(total.cache_read_input_tokens),
      cost_usd: numeric(total.cost_usd),
    },
    by_model: {},
    by_engine: {},
    top_tasks: (value.top_tasks ?? []).flatMap((item) => {
      const taskId = item.task_id;
      const title = item.title;
      const status = item.status;
      const engine = item.harness_engine;
      if (typeof taskId !== 'string' || typeof title !== 'string' || typeof status !== 'string' || typeof engine !== 'string') return [];
      return [{
        task_id: taskId,
        title,
        status,
        harness_engine: engine,
        total_tokens: numeric(item.total_tokens),
        cost_usd: numeric(item.cost_usd),
        duration_ms: typeof item.duration_ms === 'number' ? item.duration_ms : null,
      }];
    }),
  };
}
