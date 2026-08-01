import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';

// Configure the complete local Monaco build only when a text file crosses the
// lazy boundary. This preserves the existing language and worker behavior while
// keeping the editor out of every route's static dependency graph.
loader.config({ monaco });

interface Props {
  content: string;
  language: string;
  colorScheme: 'light' | 'dark';
  fontFamily: string;
  fontSize: number;
}

export default function MonacoTextViewer({ content, language, colorScheme, fontFamily, fontSize }: Props) {
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
        fontSize,
        fontFamily,
        wordWrap: 'on',
      }}
    />
  );
}
