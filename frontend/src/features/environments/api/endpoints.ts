import { api } from '@/shared/api/client';
import type {
  EnvironmentListResponse,
  EnvironmentRecord,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceListResponse,
} from '@/shared/types';
import type {
  EnvironmentCreateRequest,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceUpdateRequest,
} from '@/shared/api/transportTypes';

export const getEnvironments = (): Promise<EnvironmentListResponse> => api.get('/environments');
export const getEnvironment = (environmentId: string): Promise<EnvironmentRecord> =>
  api.get(`/environments/${environmentId}`);
export const createEnvironment = (payload: EnvironmentCreateRequest): Promise<EnvironmentRecord> =>
  api.post('/environments', payload);
export const updateEnvironment = (
  environmentId: string,
  payload: EnvironmentUpdateRequest,
): Promise<EnvironmentRecord> => api.patch(`/environments/${environmentId}`, payload);
export const deleteEnvironment = (environmentId: string): Promise<void> =>
  api.delete(`/environments/${environmentId}`);
export const detectEnvironment = (environmentId: string): Promise<EnvironmentRecord> =>
  api.post(`/environments/${environmentId}/detect`, {});

export const getProjectEnvironmentReferences = (
  projectId = 'default',
): Promise<ProjectEnvironmentReferenceListResponse> =>
  api.get(`/projects/${projectId}/environment-refs`);

export const createProjectEnvironmentReference = (
  payload: ProjectEnvironmentReferenceCreateRequest,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> =>
  api.post(`/projects/${projectId}/environment-refs`, payload);

export const updateProjectEnvironmentReference = (
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> =>
  api.patch(`/projects/${projectId}/environment-refs/${environmentId}`, payload);

export const deleteProjectEnvironmentReference = (
  environmentId: string,
  projectId = 'default',
): Promise<void> => api.delete(`/projects/${projectId}/environment-refs/${environmentId}`);
