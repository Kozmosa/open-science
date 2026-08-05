import type {
  FileEntryResponse,
  FileListResponse as TransportFileListResponse,
  FileReadResponse as TransportFileReadResponse,
  FileUploadResponse as TransportFileUploadResponse,
} from '@/generated/transport';

export type FileKind = 'file' | 'directory' | 'symlink';
export type FileEntry = { name: string; path: string; kind: FileKind; size: number | null; modified_at: string | null };
export type FileListResponse = { path: string; entries: FileEntry[] };
export type FileReadResponse = { path: string; content: string; is_binary: boolean; size: number; language: string | null; mime_type: string | null };
export type FileUploadResponse = { path: string; size: number };

export function adaptFileList(value: TransportFileListResponse): FileListResponse {
  return { path: value.path, entries: value.entries.map(adaptFileEntry) };
}

function adaptFileEntry(value: FileEntryResponse): FileEntry {
  return {
    name: value.name,
    path: value.path,
    kind: value.kind as FileKind,
    size: value.size ?? null,
    modified_at: value.modified_at ?? null,
  };
}

export function adaptFileRead(value: TransportFileReadResponse): FileReadResponse {
  return { ...value, language: value.language ?? null, mime_type: value.mime_type ?? null };
}

export function adaptFileUpload(value: TransportFileUploadResponse): FileUploadResponse {
  return value;
}
