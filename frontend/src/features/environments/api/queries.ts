import { api } from '@/shared/api/client';
import type {
  EnvironmentResponse,
  ProjectEnvironmentReferenceListResponse as TransportProjectEnvironmentReferenceListResponse,
} from '@/generated/transport';
import {
  adaptEnvironmentList,
  adaptProjectEnvironmentReferenceList,
} from '../types';
import type {
  EnvironmentListResponse,
  ProjectEnvironmentReferenceListResponse,
} from '../types';

export const getEnvironments = (): Promise<EnvironmentListResponse> =>
  api.get<{ items: EnvironmentResponse[] }>('/domain/environments').then(adaptEnvironmentList);

export const getProjectEnvironmentReferences = (
  projectId = 'default',
): Promise<ProjectEnvironmentReferenceListResponse> =>
  api.get<TransportProjectEnvironmentReferenceListResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/environment-refs`,
  ).then(adaptProjectEnvironmentReferenceList);
