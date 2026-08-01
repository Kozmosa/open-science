import { api } from '@/shared/api/client';
import type { SystemHealth } from '@/shared/types';

export const getHealth = (): Promise<SystemHealth> => api.get('/health');
