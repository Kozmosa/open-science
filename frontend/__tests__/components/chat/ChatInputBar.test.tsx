import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ChatInputBar from '../../../src/components/chat/ChatInputBar';
import { renderWithProviders } from '@/shared/test/render';

describe('ChatInputBar', () => {
  it('renders a textarea with placeholder', () => {
    renderWithProviders(<ChatInputBar onSubmit={vi.fn()} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    expect(textarea).toBeInTheDocument();
    expect(textarea.tagName).toBe('TEXTAREA');
  });

  it('renders the send button initially disabled', () => {
    renderWithProviders(<ChatInputBar onSubmit={vi.fn()} />);

    const sendButton = screen.getByRole('button', { name: /send/i });
    expect(sendButton).toBeDisabled();
  });

  it('enables send button when text is entered', async () => {
    renderWithProviders(<ChatInputBar onSubmit={vi.fn()} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    fireEvent.change(textarea, { target: { value: 'Hello' } });

    await waitFor(() => {
      const sendButton = screen.getByRole('button', { name: /send/i });
      expect(sendButton).not.toBeDisabled();
    });
  });

  it('calls onSubmit with trimmed value on send click', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<ChatInputBar onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    fireEvent.change(textarea, { target: { value: '  Hello, world!  ' } });

    const sendButton = screen.getByRole('button', { name: /send/i });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('Hello, world!');
    });
  });

  it('sends on Enter without Shift', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<ChatInputBar onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    fireEvent.change(textarea, { target: { value: 'Test message' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('Test message');
    });
  });

  it('does not send on Enter when composing (IME)', () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ChatInputBar onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    fireEvent.change(textarea, { target: { value: 'nihao' } });

    // Simulate IME composition start
    fireEvent.compositionStart(textarea);

    // Enter during composition should NOT send
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('clears the input after successful send', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<ChatInputBar onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText(/message ai/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Hello' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    await waitFor(() => {
      expect(textarea.value).toBe('');
    });
  });

  it('does not send empty or whitespace-only input', () => {
    const onSubmit = vi.fn();
    renderWithProviders(<ChatInputBar onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    fireEvent.change(textarea, { target: { value: '   ' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables input and send when disabled prop is true', () => {
    renderWithProviders(<ChatInputBar onSubmit={vi.fn()} disabled />);

    const textarea = screen.getByPlaceholderText(/message ai/i);
    expect(textarea).toBeDisabled();
  });

  it('renders action buttons (attach, web search, reason)', () => {
    renderWithProviders(<ChatInputBar onSubmit={vi.fn()} />);

    expect(screen.getByRole('button', { name: /attach/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /web search/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reason/i })).toBeInTheDocument();
  });

  it('shows scroll-to-bottom button when scrollButtonVisible is true', () => {
    const onScroll = vi.fn();
    renderWithProviders(
      <ChatInputBar onSubmit={vi.fn()} scrollButtonVisible onScrollToBottom={onScroll} />
    );

    const scrollButton = screen.getByRole('button', { name: /scroll to bottom/i });
    expect(scrollButton).toBeInTheDocument();

    fireEvent.click(scrollButton);
    expect(onScroll).toHaveBeenCalledTimes(1);
  });

});

