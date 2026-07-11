import Editor, { loader } from '@monaco-editor/react';
import { useEffect, useState } from 'react';
import * as monaco from 'monaco-editor';
import { useEditorSettings } from '@features/settings';

// Configure the complete local Monaco build only when a text file crosses the
// lazy boundary. This preserves the existing language and worker behavior while
// keeping the editor out of every route's static dependency graph.
loader.config({ monaco });

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

interface Props {
  content: string;
  language: string;
}

export default function MonacoTextViewer({ content, language }: Props) {
  const colorScheme = useSystemColorScheme();
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
