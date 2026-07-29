import { api } from '@/shared/api/client';
import type { ResourcesResponse } from '@/shared/types';

export const getResources = (): Promise<ResourcesResponse> => api.get('/resources');
