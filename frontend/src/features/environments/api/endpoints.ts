import type { EnvironmentRecord, ProjectEnvironmentReference } from '@/shared/types';
import type {
  EnvironmentCreateRequest,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReferenceCreateRequest,
  ProjectEnvironmentReferenceUpdateRequest,
} from '@/shared/api/transportTypes';
import {
  createDomainEnvironment,
  createDomainProjectEnvironmentReference,
  deleteDomainProjectEnvironmentReference,
  detectDomainEnvironment,
  disableDomainEnvironment,
  getDomainEnvironment,
  getDomainEnvironments,
  getDomainProjectEnvironmentReferences,
  updateDomainEnvironment,
  updateDomainProjectEnvironmentReference,
} from '@features/domain';

export const getEnvironments = getDomainEnvironments;
export const getEnvironment = getDomainEnvironment;
export const createEnvironment = (payload: EnvironmentCreateRequest): Promise<EnvironmentRecord> =>
  createDomainEnvironment(payload, crypto.randomUUID());
export const updateEnvironment = (
  environmentId: string,
  payload: EnvironmentUpdateRequest,
): Promise<EnvironmentRecord> => updateDomainEnvironment(environmentId, payload, crypto.randomUUID());
export const deleteEnvironment = (environmentId: string): Promise<void> =>
  disableDomainEnvironment(environmentId, crypto.randomUUID());
export const detectEnvironment = detectDomainEnvironment;

export const getProjectEnvironmentReferences = (
  projectId = 'default',
)=> getDomainProjectEnvironmentReferences(projectId);

export const createProjectEnvironmentReference = (
  payload: ProjectEnvironmentReferenceCreateRequest,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> => {
  return createDomainProjectEnvironmentReference(projectId, payload, crypto.randomUUID());
};

export const updateProjectEnvironmentReference = (
  environmentId: string,
  payload: ProjectEnvironmentReferenceUpdateRequest,
  projectId = 'default',
): Promise<ProjectEnvironmentReference> => {
  return updateDomainProjectEnvironmentReference(projectId, environmentId, payload, crypto.randomUUID());
};

export const deleteProjectEnvironmentReference = (
  environmentId: string,
  projectId = 'default',
): Promise<void> => {
  return deleteDomainProjectEnvironmentReference(projectId, environmentId, crypto.randomUUID());
};
