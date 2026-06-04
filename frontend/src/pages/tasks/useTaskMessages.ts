import { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTaskMessages } from '../../api';
import type { MessageItem, TaskOutputEvent } from '../../types';

function parseOutputPayload(content: string): Record<string, unknown> {
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

function convertOutputEventToMessage(event: TaskOutputEvent, initialPrompt?: string | null): MessageItem | null {
  const payload = parseOutputPayload(event.content);

  const base = {
    id: `${event.task_id}-${event.seq}`,
    metadata: { timestamp: event.created_at, sequence: event.seq },
  };

  switch (event.kind) {
    case 'message': {
      const content = (payload.content as string) || '';
      return {
        ...base,
        type: payload.role === 'user' || content === initialPrompt ? 'user' : 'assistant',
        content,
      };
    }
    case 'thinking':
      return {
        ...base,
        type: 'thinking',
        content: (payload.content as string) || '',
        metadata: { ...base.metadata, isFolded: true },
      };
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

function convertOutputEventsToMessages(
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

  useEffect(() => {
    setStreamMessages([]);
  }, [taskId]);

  useEffect(() => {
    const newMessages = convertOutputEventsToMessages(outputItems, initialPrompt);

    setStreamMessages((prev) => {
      const existingIds = new Set(prev.map((m) => m.id));
      const unique = newMessages.filter((m) => !existingIds.has(m.id));
      return [...prev, ...unique];
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
