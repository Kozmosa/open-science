import { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTaskMessages } from '../../api';
import type { MessageItem, TaskOutputEvent } from '../../types';

function convertOutputEventToMessage(event: TaskOutputEvent): MessageItem | null {
  let payload: Record<string, unknown> = {};
  try {
    payload = JSON.parse(event.content);
  } catch {
    payload = { content: event.content };
  }

  const base = {
    id: `${event.task_id}-${event.seq}`,
    metadata: { timestamp: event.created_at, sequence: event.seq },
  };

  switch (event.kind) {
    case 'message':
      return {
        ...base,
        type: payload.role === 'user' ? 'user' : 'assistant',
        content: (payload.content as string) || '',
      };
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

export function useTaskMessages(taskId: string | null, outputItems: TaskOutputEvent[]) {
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
    const newMessages = outputItems
      .map(convertOutputEventToMessage)
      .filter((m): m is MessageItem => m !== null);

    setStreamMessages((prev) => {
      const existingIds = new Set(prev.map((m) => m.id));
      const unique = newMessages.filter((m) => !existingIds.has(m.id));
      return [...prev, ...unique];
    });
  }, [outputItems]);

  const allMessages = useMemo(() => {
    const historyMsgs = history || [];
    const streamIds = new Set(streamMessages.map((m) => m.id));
    const dedupedHistory = historyMsgs.filter((m) => !streamIds.has(m.id));
    return [...dedupedHistory, ...streamMessages].sort(
      (a, b) => a.metadata.sequence - b.metadata.sequence
    );
  }, [history, streamMessages]);

  return { messages: allMessages };
}
