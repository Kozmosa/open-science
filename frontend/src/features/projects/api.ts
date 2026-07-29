import { api } from '@/shared/api/client';
import type {
  CollaboratorItem,
  CollaboratorListResponse,
  ProjectListResponse,
  ProjectRecord,
} from '@/shared/types';
import type {
  CollaboratorRequest,
  ProjectCreateRequest,
  ProjectUpdateRequest,
} from '@/shared/api/transportTypes';

export const getProjects = (): Promise<ProjectListResponse> => api.get('/projects');
export const getProject = (projectId: string): Promise<ProjectRecord> =>
  api.get(`/projects/${projectId}`);
export const createProject = (
  payload: ProjectCreateRequest,
  idempotencyKey?: string,
): Promise<ProjectRecord> => api.post('/projects', payload, idempotencyKey
  ? { headers: { 'Idempotency-Key': idempotencyKey } }
  : undefined);
export const updateProject = (
  projectId: string,
  payload: ProjectUpdateRequest,
  idempotencyKey: string,
): Promise<ProjectRecord> => api.patch(`/projects/${projectId}`, payload, {
  headers: { 'Idempotency-Key': idempotencyKey },
});
export const deleteProject = (projectId: string): Promise<void> => api.delete(`/projects/${projectId}`);

export const getCollaborators = (projectId: string): Promise<CollaboratorListResponse> =>
  api.get(`/projects/${projectId}/collaborators`);
export const addCollaborator = (
  projectId: string,
  payload: CollaboratorRequest,
): Promise<CollaboratorItem> => api.put(`/projects/${projectId}/collaborators`, payload);
export const removeCollaborator = (projectId: string, userId: string): Promise<void> =>
  api.delete(`/projects/${projectId}/collaborators/${userId}`);
