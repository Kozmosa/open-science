import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FileReadResponse } from '@/shared/types';
import { useT } from '@/shared/i18n';

const MonacoTextViewer = lazy(() => import('./MonacoTextViewer'));

function PdfViewer({ streamUrl, title }: { streamUrl: string; title: string }) {
  const t = useT();
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadPdf() {
      try {
        // Fetch with cookies so the backend can authenticate the iframe content.
        // A blob URL is used to bypass X-Frame-Options / CSP on the stream endpoint.
        const response = await fetch(streamUrl, { credentials: 'include' });
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`);
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        objectUrlRef.current = objectUrl;
        if (!cancelled) {
          setBlobUrl(objectUrl);
          setError(null);
        } else {
          URL.revokeObjectURL(objectUrl);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setBlobUrl(null);
        }
      }
    }

    loadPdf();

    return () => {
      cancelled = true;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [streamUrl]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        <div className="text-center">
          <p className="font-medium">{t('pages.sessions.fileBrowser.pdfLoadError')}</p>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">{error}</p>
        </div>
      </div>
    );
  }

  if (!blobUrl) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('pages.sessions.fileBrowser.loadingFile')}
      </div>
    );
  }

  return (
    <iframe
      src={blobUrl}
      title={title}
      className="h-full w-full rounded-lg border border-[var(--border)]"
    />
  );
}

interface Props {
  file: FileReadResponse | null;
  isLoading: boolean;
  pdfStreamUrl?: string;
}

export default function FileViewer({ file, isLoading, pdfStreamUrl }: Props) {
  const t = useT();

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('pages.sessions.fileBrowser.loadingFile')}
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
        {t('pages.sessions.fileBrowser.selectFile')}
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

  if (file.mime_type === 'application/pdf' && pdfStreamUrl) {
    return <PdfViewer streamUrl={pdfStreamUrl} title={file.path} />;
  }

  if (file.is_binary) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        <div className="text-center">
          <p className="font-medium">{t('pages.sessions.fileBrowser.binaryFile')}</p>
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
            {t('common.loadingEditor')}
          </div>
        }
      >
        <MonacoTextViewer content={file.content} language={file.language || 'plaintext'} />
      </Suspense>
    </div>
  );
}
