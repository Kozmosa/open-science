import { useEffect, useMemo, useRef, useState } from 'react';
import { useTaskHistory } from './useTaskHistory';
import type { MessageItem, TaskOutputEvent } from '../../types';

const SUPPRESSED_SYSTEM_SUBTYPES = new Set(['status', 'thinking_tokens']);

function shouldSuppressSystemPayload(payload: Record<string, unknown>): boolean {
  const subtype = payload.subtype;
  return typeof subtype === 'string' && SUPPRESSED_SYSTEM_SUBTYPES.has(subtype);
}

export function parseOutputPayload(content: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(content);
    const payload = typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : { content };
    const wrappedPayload = payload.payload;
    if (typeof payload.event_type === 'string' && typeof wrappedPayload === 'object' && wrappedPayload !== null) {
      return wrappedPayload as Record<string, unknown>;
    }
    return payload;
  } catch {
    return { content };
  }
}

export function convertOutputEventToMessage(
  event: TaskOutputEvent,
  initialPrompt?: string | null
): MessageItem | null {
  const payload = parseOutputPayload(event.content);

  const base = {
    id: `${event.task_id}-${event.seq}`,
    metadata: { timestamp: event.created_at, sequence: event.seq },
  };

  switch (event.kind) {
    case 'message': {
      const content = (payload.content as string) || '';
      const blockId = payload.block_id as string | undefined;
      const isDelta = payload.is_delta as boolean | undefined;
      return {
        ...base,
        type: payload.role === 'user' || content === initialPrompt ? 'user' : 'assistant',
        content,
        ...(blockId ? { metadata: { ...base.metadata, blockId, isDelta } } : {}),
      };
    }
    case 'thinking': {
      const blockId = payload.block_id as string | undefined;
      const isPartial = payload.is_partial as boolean | undefined;
      const isDelta = payload.is_delta as boolean | undefined;
      return {
        ...base,
        type: 'thinking',
        content: (payload.content as string) || '',
        metadata: {
          ...base.metadata,
          isFolded: true,
          isStreaming: isPartial ?? false,
          ...(blockId ? { blockId, isDelta } : {}),
        },
      };
    }
    case 'tool_call':
      return {
        ...base,
        type: 'tool_call',
        content: { name: payload.name, arguments: payload.arguments },
        metadata: { ...base.metadata, isFolded: true },
      };
    case 'tool_result':
      return {
        ...base,
        type: 'tool_result',
        content: { tool_use_id: payload.tool_use_id, content: payload.content },
        metadata: { ...base.metadata, isFolded: true },
      };
    case 'system':
    case 'lifecycle':
      if (shouldSuppressSystemPayload(payload)) {
        return null;
      }
      return {
        ...base,
        type: 'system_event',
        content: (payload.subtype as string) || (payload.content as string) || event.kind,
      };
    case 'stdout':
      return {
        ...base,
        type: 'assistant',
        content: (payload.content as string) || event.content,
      };
    case 'stderr':
      return {
        ...base,
        type: 'system_event',
        content: `[stderr] ${(payload.content as string) || event.content}`,
      };
    default:
      return null;
  }
}

function appendDelta(left: string, right: string): string {
  if (!left) return right;
  if (!right) return left;
  return `${left}${right}`;
}

function suppressUserEchoes(messages: MessageItem[]): MessageItem[] {
  const seenUserContent = new Set<string>();
  return messages.filter((message) => {
    if (
      message.type === 'assistant' &&
      typeof message.content === 'string' &&
      seenUserContent.has(message.content)
    ) {
      return false;
    }
    if (message.type === 'user' && typeof message.content === 'string') {
      seenUserContent.add(message.content);
    }
    return true;
  });
}

export function mergeMessages(messages: MessageItem[]): MessageItem[] {
  // 1. Sort by sequence and deduplicate. Prefer messages with blockId metadata.
  const sorted = [...messages].sort((a, b) => a.metadata.sequence - b.metadata.sequence);
  const deduped: MessageItem[] = [];
  let last: MessageItem | null = null;
  for (const message of sorted) {
    if (last && last.metadata.sequence === message.metadata.sequence) {
      // Keep the richer one (has blockId)
      if (!last.metadata.blockId && message.metadata.blockId) {
        deduped[deduped.length - 1] = message;
        last = message;
      }
      continue;
    }
    deduped.push(message);
    last = message;
  }

  // 2. Merge deltas by blockId in a single pass.
  const byBlockId = new Map<string, number>();
  const result: MessageItem[] = [];

  for (const message of deduped) {
    const blockId = message.metadata.blockId;
    const isDelta = message.metadata.isDelta === true;

    if (typeof blockId === 'string' && isDelta) {
      const existingIdx = byBlockId.get(blockId);
      if (existingIdx !== undefined) {
        const existing = result[existingIdx];
        const prevContent = typeof existing.content === 'string' ? existing.content : '';
        const deltaContent = typeof message.content === 'string' ? message.content : '';
        result[existingIdx] = {
          ...existing,
          content: appendDelta(prevContent, deltaContent),
          metadata: {
            ...existing.metadata,
            ...message.metadata,
            sequence: message.metadata.sequence,
            timestamp: message.metadata.timestamp,
          },
        };
        continue;
      }
    }

    result.push(message);
    if (typeof blockId === 'string') {
      byBlockId.set(blockId, result.length - 1);
    }
  }

  // 3. Drop assistant messages that merely echo an earlier user message.
  //    Codex and similar harnesses emit the user's message both as a wrapped
  //    `role: user` event and as a following raw assistant-looking echo.
  return suppressUserEchoes(result);
}

export function useTaskMessages(
  taskId: string | null,
  outputItems: TaskOutputEvent[],
  initialPrompt?: string | null
) {
  const { data: history, isLoading, error } = useTaskHistory(taskId);
  const [streamMessages, setStreamMessages] = useState<MessageItem[]>([]);
  const processedSeqsRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    processedSeqsRef.current = new Set();
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;

    const newEvents = outputItems.filter(
      (event) => event.task_id === taskId && !processedSeqsRef.current.has(event.seq)
    );
    if (newEvents.length === 0) return;

    const newMessages = newEvents
      .map((event) => convertOutputEventToMessage(event, initialPrompt))
      .filter((message): message is MessageItem => message !== null);

    for (const event of newEvents) {
      processedSeqsRef.current.add(event.seq);
    }

    if (newMessages.length > 0) {
      setStreamMessages((current) => mergeMessages([...current, ...newMessages]));
    }
  }, [outputItems, initialPrompt, taskId]);

  const messages = useMemo(() => {
    const historyMsgs = history || [];
    const prefix = taskId ? `${taskId}-` : null;
    const ownHistory = prefix
      ? historyMsgs.filter((message) => message.id.startsWith(prefix))
      : historyMsgs;
    return mergeMessages([...ownHistory, ...streamMessages]);
  }, [history, streamMessages, taskId]);

  return { messages, isLoading, error };
}
