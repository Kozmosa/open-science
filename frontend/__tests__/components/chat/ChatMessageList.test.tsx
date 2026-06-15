import { screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import ChatMessageList from '../../../src/components/chat/ChatMessageList';
import { renderWithProviders } from '@/shared/test/render';
import type { ChatMessage } from '../../../src/components/chat';

beforeAll(() => {
  if (typeof IntersectionObserver === 'undefined') {
    (globalThis as Record<string, unknown>).IntersectionObserver = class MockIntersectionObserver {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
      takeRecords = vi.fn(() => []);
      root = null;
      rootMargin = '';
      thresholds = [];
    };
  }
});

function makeUserMessage(id: string, content: string): ChatMessage {
  return {
    id,
    role: 'user',
    sequence: parseInt(id.split('-')[1] ?? '1', 10),
    timestamp: '2026-01-01T00:00:00Z',
    content,
  };
}

function makeAssistantMessage(
  id: string,
  content: string,
  overrides?: { isStreaming?: boolean; aborted?: boolean; thinking?: string },
): ChatMessage {
  return {
    id,
    role: 'assistant',
    sequence: parseInt(id.split('-')[1] ?? '1', 10),
    timestamp: '2026-01-01T00:00:00Z',
    content,
    isStreaming: overrides?.isStreaming ?? false,
    aborted: overrides?.aborted ?? false,
    thinking: overrides?.thinking,
  };
}

describe('ChatMessageList', () => {
  it('renders user and assistant messages', () => {
    const messages: ChatMessage[] = [
      makeUserMessage('u-1', 'Hello'),
      makeAssistantMessage('a-1', 'Hi there!'),
    ];
    renderWithProviders(
      <ChatMessageList messages={messages} hasMore={false} loadMore={vi.fn()} isLoadingMore={false} />
    );

    expect(screen.getByText('Hello')).toBeInTheDocument();
    expect(screen.getByText('Hi there!')).toBeInTheDocument();
  });

  it('renders system messages as plain text', () => {
    const messages: ChatMessage[] = [
      {
        id: 'sys-1',
        role: 'system',
        sequence: 0,
        timestamp: '2026-01-01T00:00:00Z',
        content: 'System notification',
      },
    ];
    renderWithProviders(
      <ChatMessageList messages={messages} hasMore={false} loadMore={vi.fn()} isLoadingMore={false} />
    );

    expect(screen.getByText('System notification')).toBeInTheDocument();
  });

  it('shows empty state when messages array is empty', () => {
    renderWithProviders(
      <ChatMessageList messages={[]} hasMore={false} loadMore={vi.fn()} isLoadingMore={false} />
    );

    expect(screen.getByText(/no messages/i)).toBeInTheDocument();
  });

  it('shows loading indicator in top sentinel when hasMore is true', () => {
    const messages: ChatMessage[] = [makeAssistantMessage('a-1', 'first')];
    renderWithProviders(
      <ChatMessageList
        messages={messages}
        hasMore
        loadMore={vi.fn()}
        isLoadingMore
      />
    );

    // The top sentinel should show loading text
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('shows up arrow in top sentinel when hasMore but not currently loading', () => {
    const messages: ChatMessage[] = [makeAssistantMessage('a-1', 'first')];
    renderWithProviders(
      <ChatMessageList
        messages={messages}
        hasMore
        loadMore={vi.fn()}
        isLoadingMore={false}
      />
    );

    // The top sentinel should show an upward indicator
    expect(screen.getByText('↑')).toBeInTheDocument();
  });
});
