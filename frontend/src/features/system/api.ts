import { api } from '@/shared/api/client';
import type { HealthResponse } from '@/generated/transport';

export const getHealth = (): Promise<HealthResponse> => api.get<HealthResponse>('/health');
