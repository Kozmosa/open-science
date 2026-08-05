import { api } from '@/shared/api/client';
import { idempotencyHeaders } from '@/shared/api/idempotency';
import type {
  EnvironmentResponse,
  ProjectEnvironmentReferenceResponse,
} from '@/generated/transport';
import {
  adaptEnvironment,
  adaptProjectEnvironmentReference,
  toEnvironmentCreateRequest,
  toEnvironmentUpdateRequest,
  toProjectEnvironmentReferenceCreateRequest,
  toProjectEnvironmentReferenceUpdateRequest,
} from '../types';
import type {
  EnvironmentMutationInput,
  EnvironmentRecord,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceCreateInput,
  ProjectEnvironmentReferenceUpdateInput,
} from '../types';

export const createEnvironment = (payload: EnvironmentMutationInput): Promise<EnvironmentRecord> =>
  environmentPost<EnvironmentResponse>('/domain/environments', toEnvironmentCreateRequest(payload)).then(adaptEnvironment);
export const updateEnvironment = (
  environmentId: string,
  payload: EnvironmentMutationInput,
): Promise<EnvironmentRecord> => environmentPatch<EnvironmentResponse>(
  `/domain/environments/${encodeURIComponent(environmentId)}`,
  toEnvironmentUpdateRequest(payload),
).then(adaptEnvironment);
export const deleteEnvironment = (environmentId: string): Promise<void> =>
  environmentDelete(`/domain/environments/${encodeURIComponent(environmentId)}`);
export const detectEnvironment = (environmentId: string): Promise<EnvironmentRecord> =>
  api.post<EnvironmentResponse>(`/domain/environments/${encodeURIComponent(environmentId)}/detect`, {}).then(adaptEnvironment);

export const createProjectEnvironmentReference = (
  payload: ProjectEnvironmentReferenceCreateInput,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> => {
  return environmentPost<ProjectEnvironmentReferenceResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/environment-refs`,
    toProjectEnvironmentReferenceCreateRequest(payload),
  ).then(adaptProjectEnvironmentReference);
};

export const updateProjectEnvironmentReference = (
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateInput,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> => {
  return environmentPatch<ProjectEnvironmentReferenceResponse>(
    `/domain/projects/${encodeURIComponent(projectId)}/environment-refs/${encodeURIComponent(environmentId)}`,
    toProjectEnvironmentReferenceUpdateRequest(payload),
  ).then(adaptProjectEnvironmentReference);
};

export const deleteProjectEnvironmentReference = (
  environmentId: string,
  projectId = 'default',
): Promise<void> => {
  return environmentDelete(`/domain/projects/${encodeURIComponent(projectId)}/environment-refs/${encodeURIComponent(environmentId)}`);
};

function environmentPost<TResponse>(path: string, body: unknown): Promise<TResponse> {
  return api.post(path, body, { headers: idempotencyHeaders(crypto.randomUUID()) });
}

function environmentPatch<TResponse>(path: string, body: unknown): Promise<TResponse> {
  return api.patch(path, body, { headers: idempotencyHeaders(crypto.randomUUID()) });
}

function environmentDelete<TResponse = void>(path: string): Promise<TResponse> {
  return api.delete(path, { headers: idempotencyHeaders(crypto.randomUUID()) });
}
