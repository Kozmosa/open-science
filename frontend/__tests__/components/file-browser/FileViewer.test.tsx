import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/shared/i18n';
import type { FileReadResponse } from '@/shared/types';
import FileViewer from '../../../src/components/file-browser/FileViewer';

const lazyModuleState = vi.hoisted(() => ({ loads: 0 }));

vi.mock('../../../src/components/file-browser/MonacoTextViewer', () => {
  lazyModuleState.loads += 1;
  return {
    default: ({ content, language }: { content: string; language: string }) => (
      <div data-testid="monaco-text-viewer" data-language={language}>
        {content}
      </div>
    ),
  };
});

const fileBase: FileReadResponse = {
  path: 'example.txt',
  content: '',
  is_binary: false,
  size: 0,
  language: null,
  mime_type: 'text/plain',
};

describe('FileViewer', () => {
  it('loads Monaco only after a text file is selected', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));
    const { rerender } = render(<FileViewer file={null} isLoading={false} />, {
      wrapper: ({ children }) => <LocaleProvider initialLocale="en">{children}</LocaleProvider>,
    });

    expect(lazyModuleState.loads).toBe(0);

    rerender(
      <FileViewer
        file={{
          ...fileBase,
          path: 'figure.png',
          content: 'aW1hZ2U=',
          is_binary: true,
          size: 6,
          mime_type: 'image/png',
        }}
        isLoading={false}
      />
    );
    expect(screen.getByRole('img', { name: 'figure.png' })).toBeInTheDocument();
    expect(lazyModuleState.loads).toBe(0);

    rerender(
      <FileViewer
        file={{
          ...fileBase,
          path: 'archive.bin',
          is_binary: true,
          size: 2048,
          mime_type: 'application/octet-stream',
        }}
        isLoading={false}
      />
    );
    expect(screen.getByText('Binary file')).toBeInTheDocument();
    expect(lazyModuleState.loads).toBe(0);

    rerender(
      <FileViewer
        file={{
          ...fileBase,
          path: 'paper.pdf',
          is_binary: true,
          size: 4096,
          mime_type: 'application/pdf',
        }}
        isLoading={false}
        pdfStreamUrl="/api/files/stream/paper.pdf"
      />
    );
    expect(screen.getByText('Loading file...')).toBeInTheDocument();
    expect(lazyModuleState.loads).toBe(0);

    rerender(
      <FileViewer
        file={{
          ...fileBase,
          path: 'README.md',
          content: '# OpenScience',
          size: 13,
          language: 'markdown',
          mime_type: 'text/markdown',
        }}
        isLoading={false}
      />
    );

    expect(await screen.findByTestId('monaco-text-viewer')).toHaveAttribute(
      'data-language',
      'markdown'
    );
    expect(lazyModuleState.loads).toBe(1);
  });
});
