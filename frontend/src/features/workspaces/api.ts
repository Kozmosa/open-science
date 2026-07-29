import { api } from '@/shared/api/client';
import type {
  FileListResponse,
  FileReadResponse,
  FileUploadResponse,
  WorkspaceListResponse,
  WorkspaceRecord,
} from '@/shared/types';
import type { WorkspaceCreateRequest, WorkspaceUpdateRequest } from '@/shared/api/transportTypes';

export const getWorkspaces = (): Promise<WorkspaceListResponse> => api.get('/workspaces');
export const getWorkspace = (workspaceId: string): Promise<WorkspaceRecord> =>
  api.get(`/workspaces/${workspaceId}`);
export const createWorkspace = (payload: WorkspaceCreateRequest): Promise<WorkspaceRecord> =>
  api.post('/workspaces', payload);
export const updateWorkspace = (
  workspaceId: string,
  payload: WorkspaceUpdateRequest,
  idempotencyKey: string,
): Promise<WorkspaceRecord> => api.patch(`/workspaces/${workspaceId}`, payload, {
  headers: { 'Idempotency-Key': idempotencyKey },
});
export const deleteWorkspace = (workspaceId: string): Promise<void> =>
  api.delete(`/workspaces/${workspaceId}`);
export const unregisterWorkspace = (workspaceId: string, idempotencyKey: string): Promise<void> =>
  api.post(`/workspaces/${workspaceId}/unregister`, {}, {
    headers: { 'Idempotency-Key': idempotencyKey },
  });

function fileQuery(environmentId: string, path: string, workspaceId?: string): string {
  const search = new URLSearchParams({ environment_id: environmentId, path });
  if (workspaceId) search.set('workspace_id', workspaceId);
  return search.toString();
}

export const listFiles = (
  environmentId: string,
  path = '',
  workspaceId?: string,
): Promise<FileListResponse> => api.get(`/files/list?${fileQuery(environmentId, path, workspaceId)}`);

export const readFile = (
  environmentId: string,
  path: string,
  workspaceId?: string,
): Promise<FileReadResponse> => api.get(`/files/read?${fileQuery(environmentId, path, workspaceId)}`);

export const buildFileStreamUrl = (
  environmentId: string,
  path: string,
  workspaceId?: string,
): string => `/api/files/stream?${fileQuery(environmentId, path, workspaceId)}`;

export const uploadFile = (params: {
  environmentId: string;
  path: string;
  workspaceId?: string;
  file: File;
}): Promise<FileUploadResponse> => {
  const formData = new FormData();
  formData.append('environment_id', params.environmentId);
  formData.append('path', params.path);
  if (params.workspaceId) formData.append('workspace_id', params.workspaceId);
  formData.append('file', params.file);
  return api.post('/files/upload', formData);
};
