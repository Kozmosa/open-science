import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AssistantMessage, MessageBlock } from '../../../src/pages/tasks/MessageBlocks';
import { renderWithProviders } from '../../../src/test/render';
import type { MessageItem } from '../../../src/types';

function message(content: string): MessageItem {
  return {
    id: 'msg-1',
    type: 'assistant',
    content,
    metadata: {
      sequence: 1,
      timestamp: '2026-01-01T00:00:00Z',
    },
  };
}

describe('MessageBlocks workspace file links', () => {
  it('renders absolute workspace markdown links as file browser links', () => {
    renderWithProviders(
      <AssistantMessage
        message={message(
          '已保存文献导读到：\n\n[docs/literature/2606.04620-overview.md](/home/xuyang/.ainrf_workspaces/default/docs/literature/2606.04620-overview.md)'
        )}
      />
    );

    const link = screen.getByRole('link', { name: 'docs/literature/2606.04620-overview.md' });
    expect(link).toHaveAttribute(
      'href',
      '/workspace-browser?workspace_id=workspace-default&path=docs%2Fliterature%2F2606.04620-overview.md'
    );
  });

  it('renders tool result workspace links consistently', () => {
    renderWithProviders(
      <MessageBlock
        message={{
          id: 'msg-2',
          type: 'tool_result',
          content: 'saved: [guide](/home/xuyang/.ainrf_workspaces/default/docs/literature/guide.md)',
          metadata: { sequence: 2, timestamp: '2026-01-01T00:00:00Z', isFolded: false },
        }}
      />
    );

    const link = screen.getByRole('link', { name: 'guide' });
    expect(link).toHaveAttribute('href', '/workspace-browser?workspace_id=workspace-default&path=docs%2Fliterature%2Fguide.md');
  });
});
