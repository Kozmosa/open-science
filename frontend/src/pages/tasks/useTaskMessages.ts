import { useState, useEffect, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTaskMessages } from '../../api';
import type { MessageItem, TaskOutputEvent } from '../../types';

export function parseOutputPayload(content: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(content);
    const payload = typeof parsed === 'object' && parsed !== null ? parsed as Record<string, unknown> : { content };
    const wrappedPayload = payload.payload;
    if (typeof payload.event_type === 'string' && typeof wrappedPayload === 'object' && wrappedPayload !== null) {
      return wrappedPayload as Record<string, unknown>;
    }
    return payload;
  } catch {
    return { content };
  }
}

export function convertOutputEventToMessage(event: TaskOutputEvent, initialPrompt?: string | null): MessageItem | null {
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
          isFolded: isPartial ? false : true,
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

export function convertOutputEventsToMessages(
  events: TaskOutputEvent[],
  initialPrompt?: string | null
): MessageItem[] {
  const messages: MessageItem[] = [];
  const seenUserContent = new Set<string>();
  for (const event of events) {
    const message = convertOutputEventToMessage(event, initialPrompt);
    if (message === null) {
      continue;
    }
    if (message.type === 'assistant' && typeof message.content === 'string' && seenUserContent.has(message.content)) {
      continue;
    }
    if (message.type === 'user' && typeof message.content === 'string') {
      seenUserContent.add(message.content);
    }
    messages.push(message);
  }
  return messages;
}

function suppressUserEchoes(messages: MessageItem[]): MessageItem[] {
  const seenUserContent = new Set<string>();
  const result: MessageItem[] = [];
  for (const message of messages) {
    if (message.type === 'assistant' && typeof message.content === 'string' && seenUserContent.has(message.content)) {
      continue;
    }
    if (message.type === 'user' && typeof message.content === 'string') {
      seenUserContent.add(message.content);
    }
    result.push(message);
  }
  return result;
}

async function fetchAllMessages(taskId: string): Promise<MessageItem[]> {
  const allMessages: MessageItem[] = [];
  let afterSeq = 0;
  const limit = 200;

  while (true) {
    const page = await getTaskMessages(taskId, afterSeq, limit);
    allMessages.push(...page.messages);
    if (!page.has_more || page.next_sequence == null) {
      break;
    }
    afterSeq = page.next_sequence;
  }

  return allMessages;
}

export function useTaskMessages(taskId: string | null, outputItems: TaskOutputEvent[], initialPrompt?: string | null) {
  const { data: history } = useQuery({
    queryKey: ['task-messages', taskId],
    queryFn: () => fetchAllMessages(taskId!),
    enabled: !!taskId,
  });

  const [streamMessages, setStreamMessages] = useState<MessageItem[]>([]);
  const lastProcessedSeqRef = useRef<number>(0);

  useEffect(() => {
    setStreamMessages([]);
    lastProcessedSeqRef.current = 0;
  }, [taskId]);

  useEffect(() => {
    // Only convert events we haven't processed yet
    const newEvents = outputItems.filter((e) => e.seq > lastProcessedSeqRef.current);
    if (newEvents.length === 0) return;

    const newMessages = convertOutputEventsToMessages(newEvents, initialPrompt);
    lastProcessedSeqRef.current = newEvents[newEvents.length - 1].seq;

    setStreamMessages((prev) => {
      // Build a map of existing messages by blockId for quick lookup
      const byBlockId = new Map<string, number>();
      prev.forEach((m, i) => {
        const bid = m.metadata.blockId;
        if (bid) byBlockId.set(bid, i);
      });

      const result = [...prev];
      for (const msg of newMessages) {
        const bid = msg.metadata.blockId;
        if (bid) {
          const existingIdx = byBlockId.get(bid);
          if (existingIdx !== undefined) {
            const isDelta = msg.metadata.isDelta === true;
            const prevContent = typeof result[existingIdx].content === 'string'
              ? result[existingIdx].content as string
              : '';
            const newContent = isDelta
              ? prevContent + (typeof msg.content === 'string' ? msg.content : '')
              : msg.content;
            result[existingIdx] = {
              ...result[existingIdx],
              content: newContent,
              metadata: { ...result[existingIdx].metadata, ...msg.metadata },
            };
            continue;
          }
          byBlockId.set(bid, result.length);
        }
        // New message — add only if not already present by id
        const existingIds = new Set(result.map((m) => m.id));
        if (!existingIds.has(msg.id)) {
          result.push(msg);
        }
      }
      return result;
    });
  }, [outputItems, initialPrompt]);

  const allMessages = useMemo(() => {
    const historyMsgs = history || [];
    const streamIds = new Set(streamMessages.map((m) => m.id));
    const dedupedHistory = historyMsgs.filter((m) => !streamIds.has(m.id));
    const sortedMessages = [...dedupedHistory, ...streamMessages].sort(
      (a, b) => a.metadata.sequence - b.metadata.sequence
    );
    return suppressUserEchoes(sortedMessages);
  }, [history, streamMessages]);

  return { messages: allMessages };
}
