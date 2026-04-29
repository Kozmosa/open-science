import { lazy, Suspense } from 'react';
import type { FileReadResponse } from '../../types';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

interface FileViewerProps {
  file: FileReadResponse | null;
  isLoading: boolean;
}

export default function FileViewer({ file, isLoading }: FileViewerProps) {
  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        Loading file...
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        Select a file to view its contents
      </div>
    );
  }

  if (file.is_binary && file.mime_type?.startsWith('image/')) {
    return (
      <div className="flex h-full items-center justify-center overflow-auto p-4">
        <img
          src={`data:${file.mime_type};base64,${file.content}`}
          alt={file.path}
          className="max-h-full max-w-full rounded-lg object-contain"
        />
      </div>
    );
  }

  if (file.is_binary) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        <div className="text-center">
          <p className="font-medium">Binary file</p>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            {file.path} · {(file.size / 1024).toFixed(1)} KB
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <Suspense
        fallback={
          <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
            Loading editor...
          </div>
        }
      >
        <MonacoEditor
          height="100%"
          language={file.language || 'plaintext'}
          value={file.content}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
            wordWrap: 'on',
          }}
        />
      </Suspense>
    </div>
  );
}
