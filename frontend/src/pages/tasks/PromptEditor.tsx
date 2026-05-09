import Editor from '@monaco-editor/react';
import { useMonacoTheme } from '../../hooks/useMonacoTheme';

interface Props {
  content: string;
}

export default function PromptEditor({ content }: Props) {
  const theme = useMonacoTheme();

  return (
    <div className="border-t border-[var(--border)]">
      <Editor
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
    </div>
  );
}
