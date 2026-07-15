import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import { useEditorSettings } from '@features/settings';
import { useResolvedOsciTheme } from '@/shared/hooks/useResolvedOsciTheme';

// Configure the complete local Monaco build only when a text file crosses the
// lazy boundary. This preserves the existing language and worker behavior while
// keeping the editor out of every route's static dependency graph.
loader.config({ monaco });

interface Props {
  content: string;
  language: string;
}

export default function MonacoTextViewer({ content, language }: Props) {
  const colorScheme = useResolvedOsciTheme();
  const editorSettings = useEditorSettings();

  return (
    <Editor
      height="100%"
      language={language}
      value={content}
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
  );
}
