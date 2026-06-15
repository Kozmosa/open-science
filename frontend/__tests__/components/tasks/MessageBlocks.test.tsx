import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ChatAssistantMessage, ChatThinkingBlock, ChatToolCallBlock } from '../../../src/components/chat';
import { renderWithProviders } from '@/shared/test/render';
import type { ChatAssistantMessage as ChatAssistantMessageType } from '../../../src/components/chat';

function assistantMessage(content: string, overrides?: Partial<ChatAssistantMessageType>): ChatAssistantMessageType {
  return {
    id: 'msg-1',
    role: 'assistant',
    sequence: 1,
    timestamp: '2026-01-01T00:00:00Z',
    content,
    isStreaming: false,
    aborted: false,
    ...overrides,
  };
}

describe('Chat assistant workspace file links', () => {
  it('renders absolute workspace markdown links as file browser links', () => {
    renderWithProviders(
      <ChatAssistantMessage
        message={assistantMessage(
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
});

describe('ChatThinkingBlock behavior', () => {
  it('starts collapsed and only renders content after expand', () => {
    renderWithProviders(
      <ChatThinkingBlock content="streamed reasoning" />
    );

    const toggle = screen.getByRole('button', { name: /thinking process/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('streamed reasoning')).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(screen.getByText('streamed reasoning')).toBeInTheDocument();
  });
});

describe('ChatToolCallBlock behavior', () => {
  it('renders a tool call button and expands to show arguments and result', () => {
    renderWithProviders(
      <ChatToolCallBlock
        call={{
          id: 'tc-1',
          name: 'commandExecution',
          args: JSON.stringify({ cmd: 'ls' }, null, 2),
          result: 'output',
          status: 'success',
        }}
      />
    );

    const toggle = screen.getByRole('button', { name: 'commandExecution' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Arguments')).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(screen.getByText('Arguments')).toBeInTheDocument();
    expect(screen.getByText('Result')).toBeInTheDocument();
    expect(screen.getByText('output')).toBeInTheDocument();
  });

  it('shows running state when no result is provided', () => {
    renderWithProviders(
      <ChatToolCallBlock
        call={{
          id: 'tc-2',
          name: 'search',
          args: JSON.stringify({ query: 'test' }),
          status: 'running',
        }}
      />
    );

    expect(screen.getByRole('button', { name: 'search' })).toBeInTheDocument();
    expect(screen.queryByText('Result')).not.toBeInTheDocument();
  });
});

describe('ChatAssistantMessage tool calls', () => {
  it('renders grouped tool calls inside an assistant turn', () => {
    renderWithProviders(
      <ChatAssistantMessage
        message={assistantMessage('Done.', {
          toolCalls: [
            { id: 'tc-1', name: 'commandExecution', args: '{}', result: 'ok', status: 'success' },
            { id: 'tc-2', name: 'readFile', args: '{}', status: 'running' },
          ],
        })}
      />
    );

    const summary = screen.getByRole('button', { name: '2 tools called' });
    expect(summary).toBeInTheDocument();
    expect(screen.getByText('Done.')).toBeInTheDocument();

    fireEvent.click(summary);

    expect(screen.getByRole('button', { name: 'commandExecution' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'readFile' })).toBeInTheDocument();
  });

  it('renders aborted state with copy and retry actions', () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <ChatAssistantMessage
        message={assistantMessage('', { aborted: true })}
        onRetry={onRetry}
      />
    );

    const retryButton = screen.getByRole('button', { name: /retry/i });
    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
