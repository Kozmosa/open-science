import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import type { FileReadResponse } from '../../types';
import { useEditorSettings } from '../../settings';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

function base64ToBlobUrl(base64: string, mimeType: string): string {
  const byteChars = atob(base64);
  const bytes = new Uint8Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) {
    bytes[i] = byteChars.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mimeType });
  return URL.createObjectURL(blob);
}

function useSystemColorScheme(): 'light' | 'dark' {
  const [scheme, setScheme] = useState<'light' | 'dark'>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return 'light';
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return;
    }
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (event: MediaQueryListEvent) => {
      setScheme(event.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  return scheme;
}

function PdfViewer({ file }: { file: FileReadResponse }) {
  const blobUrl = useMemo(
    () => base64ToBlobUrl(file.content, 'application/pdf'),
    [file.content]
  );

  useEffect(() => {
    return () => URL.revokeObjectURL(blobUrl);
  }, [blobUrl]);

  return (
    <iframe
      src={blobUrl}
      title={file.path}
      className="h-full w-full rounded-lg border border-[var(--border)]"
    />
  );
}

interface Props {
  file: FileReadResponse | null;
  isLoading: boolean;
}

export default function FileViewer({ file, isLoading }: Props) {
  const colorScheme = useSystemColorScheme();
  const editorSettings = useEditorSettings();

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

  if (file.mime_type === 'application/pdf') {
    return <PdfViewer file={file} />;
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
          theme={colorScheme === 'dark' ? 'vs-dark' : 'vs'}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: editorSettings.fontSize,
            fontFamily: editorSettings.fontFamily,
            wordWrap: 'on',
          }}
        />
      </Suspense>
    </div>
  );
}
