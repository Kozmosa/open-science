import { describe, expect, it } from 'vitest';
import { groupMessages } from '../../../src/components/chat/groupMessages';
import type { MessageItem } from '../../../src/components/chat';

function user(seq: number, content: string): MessageItem {
  return {
    id: `u-${seq}`,
    type: 'user',
    content,
    metadata: { timestamp: '2026-01-01T00:00:00Z', sequence: seq },
  };
}

function assistant(seq: number, content: string, overrides?: Partial<MessageItem>): MessageItem {
  const metadata = {
    timestamp: '2026-01-01T00:00:00Z',
    sequence: seq,
    sourceKind: 'message' as const,
    ...overrides?.metadata,
  };
  return {
    id: `a-${seq}`,
    type: 'assistant',
    content,
    metadata,
  };
}

function thinking(seq: number, content: string, isStreaming: boolean = false): MessageItem {
  return {
    id: `t-${seq}`,
    type: 'thinking',
    content,
    metadata: { timestamp: '2026-01-01T00:00:00Z', sequence: seq, isStreaming },
  };
}

function toolCall(seq: number, id: string, name: string, args?: unknown): MessageItem {
  return {
    id: `tc-${seq}`,
    type: 'tool_call',
    content: { id, name, arguments: args ?? { query: 'test' } },
    metadata: { timestamp: '2026-01-01T00:00:00Z', sequence: seq },
  };
}

function toolResult(seq: number, toolUseId: string, content: unknown): MessageItem {
  return {
    id: `tr-${seq}`,
    type: 'tool_result',
    content: { tool_use_id: toolUseId, content },
    metadata: { timestamp: '2026-01-01T00:00:00Z', sequence: seq },
  };
}

describe('groupMessages', () => {
  it('keeps user and system messages as standalone turns', () => {
    const result = groupMessages([
      user(1, 'hello'),
      {
        id: 's-2',
        type: 'system_event',
        content: 'system note',
        metadata: { timestamp: '2026-01-01T00:00:00Z', sequence: 2 },
      },
      user(3, 'again'),
    ]);

    expect(result).toHaveLength(3);
    expect(result[0]).toMatchObject({ role: 'user', content: 'hello' });
    expect(result[1]).toMatchObject({ role: 'system', content: 'system note' });
    expect(result[2]).toMatchObject({ role: 'user', content: 'again' });
  });

  it('merges thinking, tool calls, and assistant content into one assistant turn', () => {
    const result = groupMessages([
      thinking(1, 'planning...'),
      toolCall(2, 'tc-1', 'search'),
      toolResult(3, 'tc-1', { found: true }),
      assistant(4, 'Here is the answer.', { metadata: { sourceKind: 'message' } }),
    ]);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      role: 'assistant',
      content: 'Here is the answer.',
      thinking: 'planning...',
      isStreaming: false,
      aborted: false,
    });

    const toolCalls = (result[0] as { toolCalls?: unknown }).toolCalls as Array<{
      id: string;
      name: string;
      status: string;
      result: string;
    }>;
    expect(toolCalls).toHaveLength(1);
    expect(toolCalls[0]).toMatchObject({
      id: 'tc-1',
      name: 'search',
      status: 'success',
      result: JSON.stringify({ found: true }, null, 2),
    });
  });

  it('pairs orphan tool results with the first running tool call', () => {
    const result = groupMessages([
      toolCall(1, 'tc-1', 'exec', { cmd: 'ls' }),
      toolResult(2, 'unknown-id', 'output'),
    ]);

    const msg = result[0] as { toolCalls?: Array<{ result?: string; status: string }> };
    expect(msg.toolCalls?.[0].result).toBe('output');
    expect(msg.toolCalls?.[0].status).toBe('success');
  });

  it('marks assistant turn as aborted when it finishes without content', () => {
    const result = groupMessages([
      thinking(1, 'reasoning', false),
    ]);

    expect(result[0]).toMatchObject({
      role: 'assistant',
      content: undefined,
      thinking: 'reasoning',
      isStreaming: false,
      aborted: true,
    });
  });

  it('starts a new assistant turn after content when another reasoning burst arrives', () => {
    const result = groupMessages([
      assistant(1, 'first answer', { metadata: { sourceKind: 'message' } }),
      thinking(2, 'second reasoning'),
      assistant(3, 'second answer', { metadata: { sourceKind: 'message' } }),
    ]);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ content: 'first answer' });
    expect(result[1]).toMatchObject({ content: 'second answer', thinking: 'second reasoning' });
  });
});
