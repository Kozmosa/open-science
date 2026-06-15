import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChatUserMessage from '../../../src/components/chat/ChatUserMessage';
import type { ChatUserMessage as ChatUserMessageType } from '../../../src/components/chat';

function userMessage(content: string): ChatUserMessageType {
  return {
    id: 'msg-u1',
    role: 'user' as const,
    sequence: 1,
    timestamp: '2026-01-01T00:00:00Z',
    content,
  };
}

describe('ChatUserMessage', () => {
  it('renders the user message content', () => {
    render(<ChatUserMessage message={userMessage('Hello, AI!')} />);
    expect(screen.getByText('Hello, AI!')).toBeInTheDocument();
  });

  it('preserves whitespace with pre-wrap for multi-line messages', () => {
    render(<ChatUserMessage message={userMessage('Line 1\nLine 2\nLine 3')} />);
    const bubble = screen.getByText(/Line 1/);
    expect(bubble).toHaveClass('whitespace-pre-wrap');
  });

  it('renders long messages without truncation', () => {
    const longContent = 'A'.repeat(500);
    render(<ChatUserMessage message={userMessage(longContent)} />);
    expect(screen.getByText(longContent)).toBeInTheDocument();
  });

  it('aligns the message to the end (user side)', () => {
    render(<ChatUserMessage message={userMessage('test')} />);
    const wrapper = screen.getByText('test').closest('.flex-col');
    expect(wrapper).toHaveClass('items-end');
  });
});
