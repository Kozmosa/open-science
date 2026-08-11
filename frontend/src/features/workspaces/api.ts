import { api } from '@/shared/api/client';
import type { FileListResponse as TransportFileListResponse, FileReadResponse as TransportFileReadResponse } from '@/generated/transport';
import { adaptFileList, adaptFileRead } from './types';
import type { FileListResponse, FileReadResponse } from './types';

function fileQuery(environmentId: string, path: string, workspaceId?: string): string {
  const search = new URLSearchParams({ environment_id: environmentId, path });
  if (workspaceId) search.set('workspace_id', workspaceId);
  return search.toString();
}

export const listFiles = (
  environmentId: string,
  path = '',
  workspaceId?: string,
): Promise<FileListResponse> => api.get<TransportFileListResponse>(`/files/list?${fileQuery(environmentId, path, workspaceId)}`).then(adaptFileList);

export const readFile = (
  environmentId: string,
  path: string,
  workspaceId?: string,
): Promise<FileReadResponse> => api.get<TransportFileReadResponse>(`/files/read?${fileQuery(environmentId, path, workspaceId)}`).then(adaptFileRead);

export const buildFileStreamUrl = (
  environmentId: string,
  path: string,
  workspaceId?: string,
): string => `/api/files/stream?${fileQuery(environmentId, path, workspaceId)}`;
