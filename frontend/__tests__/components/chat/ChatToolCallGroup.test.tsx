import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChatToolCallGroup from '../../../src/components/chat/ChatToolCallGroup';
import { renderWithProviders } from '@/shared/test/render';
import type { ChatToolCallData } from '../../../src/components/chat';

function makeCall(overrides?: Partial<ChatToolCallData>): ChatToolCallData {
  return {
    id: 'tc-1',
    name: 'commandExecution',
    args: JSON.stringify({ cmd: 'ls' }),
    result: 'file1.txt\nfile2.txt',
    status: 'success',
    ...overrides,
  };
}

describe('ChatToolCallGroup', () => {
  it('delegates a single tool call to ChatToolCallBlock directly (no summary card)', () => {
    const calls = [makeCall()];
    renderWithProviders(<ChatToolCallGroup calls={calls} />);

    // Single call renders the block inline, not a summary "N tools called"
    expect(screen.getByRole('button', { name: 'commandExecution' })).toBeInTheDocument();
    expect(screen.queryByText(/tools called/i)).not.toBeInTheDocument();
  });

  it('shows a summary card for multiple tool calls', () => {
    const calls = [
      makeCall({ id: 'tc-1', name: 'readFile' }),
      makeCall({ id: 'tc-2', name: 'writeFile' }),
    ];
    renderWithProviders(<ChatToolCallGroup calls={calls} />);

    const summary = screen.getByRole('button', { name: /2 tools called/i });
    expect(summary).toBeInTheDocument();
  });

  it('expands to show individual tool call names after clicking summary', () => {
    const calls = [
      makeCall({ id: 'tc-a', name: 'readFile', status: 'success' }),
      makeCall({ id: 'tc-b', name: 'writeFile', status: 'running' }),
    ];
    renderWithProviders(<ChatToolCallGroup calls={calls} />);

    fireEvent.click(screen.getByRole('button', { name: /2 tools called/i }));

    // After expansion, individual calls are visible
    expect(screen.getByRole('button', { name: 'readFile' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'writeFile' })).toBeInTheDocument();
  });

  it('reflects overall running status in summary card when any call is running', () => {
    const calls = [
      makeCall({ id: 'tc-1', name: 'search', status: 'success' }),
      makeCall({ id: 'tc-2', name: 'index', status: 'running' }),
    ];
    renderWithProviders(<ChatToolCallGroup calls={calls} />);

    // Should still show summary (2 tool calls) with running state
    const summary = screen.getByRole('button', { name: /2 tools called/i });
    expect(summary).toBeInTheDocument();
  });

  it('collapses back to summary after expanding and clicking collapse', () => {
    const calls = [
      makeCall({ id: 'tc-1', name: 'readFile' }),
      makeCall({ id: 'tc-2', name: 'writeFile' }),
    ];
    renderWithProviders(<ChatToolCallGroup calls={calls} />);

    // Expand
    fireEvent.click(screen.getByRole('button', { name: /2 tools called/i }));
    expect(screen.getByText(/collapse/i)).toBeInTheDocument();

    // Collapse
    fireEvent.click(screen.getByText(/collapse/i));

    // Individual calls should no longer be named (they exist but stacked behind summary)
    const summary = screen.getByRole('button', { name: /2 tools called/i });
    expect(summary).toBeInTheDocument();
  });
});
