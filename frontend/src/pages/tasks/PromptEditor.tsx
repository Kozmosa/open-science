import { lazy, Suspense } from 'react';
import { useMonacoTheme } from '../../hooks/useMonacoTheme';

const MonacoEditor = lazy(() => import('@monaco-editor/react'));

interface Props {
  content: string;
}

function EditorFallback() {
  return (
    <div className="border-t border-[var(--border)] flex items-center justify-center h-[300px] text-sm text-[var(--text-secondary)]">
      Loading editor...
    </div>
  );
}

export default function PromptEditor({ content }: Props) {
  const theme = useMonacoTheme();

  return (
    <div className="border-t border-[var(--border)]">
      <Suspense fallback={<EditorFallback />}>
        <MonacoEditor
          height="300px"
          language="plaintext"
          value={content}
          theme={theme}
          options={{
            readOnly: true,
            wordWrap: 'on',
            minimap: { enabled: false },
            lineNumbers: 'off',
            scrollBeyondLastLine: false,
            fontSize: 12,
            padding: { top: 12, bottom: 12 },
          }}
        />
      </Suspense>
    </div>
  );
}
