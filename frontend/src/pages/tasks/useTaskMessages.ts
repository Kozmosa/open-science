import { useState, useEffect, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTaskMessages } from '../../api';
import type { MessageItem, TaskOutputEvent } from '../../types';

const SUPPRESSED_SYSTEM_SUBTYPES = new Set(['status', 'thinking_tokens']);

const THINKING_STREAM_FLUSH_MS = 96;

function isDeferredThinkingMessage(message: MessageItem): boolean {
  return message.type === 'thinking' && message.metadata.isStreaming === true && message.metadata.isDelta === true;
}

export function shouldDeferMessageBatch(messages: MessageItem[]): boolean {
  return messages.length > 0 && messages.every(isDeferredThinkingMessage);
}

function shouldSuppressSystemPayload(payload: Record<string, unknown>): boolean {
  const subtype = payload.subtype;
  return typeof subtype === 'string' && SUPPRESSED_SYSTEM_SUBTYPES.has(subtype);
}


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

function joinThinkingContent(left: string, right: string): string {
  if (!left) return right;
  if (!right) return left;
  return `${left}\n\n${right}`;
}

export function mergeAdjacentThinkingMessages(messages: MessageItem[]): MessageItem[] {
  const merged: MessageItem[] = [];
  for (const message of messages) {
    const previous = merged[merged.length - 1];
    if (previous?.type === 'thinking' && message.type === 'thinking') {
      const previousContent = typeof previous.content === 'string' ? previous.content : '';
      const currentContent = typeof message.content === 'string' ? message.content : '';
      merged[merged.length - 1] = {
        ...previous,
        content: joinThinkingContent(previousContent, currentContent),
        metadata: {
          ...previous.metadata,
          timestamp: message.metadata.timestamp,
          sequence: message.metadata.sequence,
          isFolded: true,
          isStreaming: message.metadata.isStreaming ?? previous.metadata.isStreaming ?? false,
          blockId: previous.metadata.blockId ?? message.metadata.blockId,
        },
      };
      continue;
    }
    merged.push(message);
  }
  return merged;
}

export function mergeStreamMessages(previousMessages: MessageItem[], newMessages: MessageItem[]): MessageItem[] {
  const byBlockId = new Map<string, number>();
  previousMessages.forEach((message, index) => {
    const blockId = message.metadata.blockId;
    if (blockId) {
      byBlockId.set(blockId, index);
    }
  });

  const existingIds = new Set(previousMessages.map((message) => message.id));
  const result = [...previousMessages];
  for (const message of newMessages) {
    const blockId = message.metadata.blockId;
    if (blockId) {
      const existingIdx = byBlockId.get(blockId);
      if (existingIdx !== undefined) {
        const isDelta = message.metadata.isDelta === true;
        const previousContent = typeof result[existingIdx].content === 'string'
          ? result[existingIdx].content as string
          : '';
        const nextContent = isDelta
          ? previousContent + (typeof message.content === 'string' ? message.content : '')
          : message.content;
        result[existingIdx] = {
          ...result[existingIdx],
          content: nextContent,
          metadata: { ...result[existingIdx].metadata, ...message.metadata },
        };
        continue;
      }
      byBlockId.set(blockId, result.length);
    }
    if (!existingIds.has(message.id)) {
      existingIds.add(message.id);
      result.push(message);
    }
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
  const boundTaskIdRef = useRef<string | null>(null);
  const pendingMessagesRef = useRef<MessageItem[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const flushPendingMessages = () => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (pendingMessagesRef.current.length === 0) {
      return;
    }
    const pendingMessages = pendingMessagesRef.current;
    pendingMessagesRef.current = [];
    setStreamMessages((previousMessages) => mergeStreamMessages(previousMessages, pendingMessages));
  };

  useEffect(() => {
    return () => {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }
    };
  }, []);

  // Single effect: reset on task change, then convert new events.
  useEffect(() => {
    const taskChanged = taskId !== boundTaskIdRef.current;
    if (taskChanged) {
      boundTaskIdRef.current = taskId ?? null;
      pendingMessagesRef.current = [];
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      setStreamMessages([]);
      lastProcessedSeqRef.current = 0;
      // outputItems is owned by useTaskOutputStream, which clears it in its
      // own effect (runs after commit). On the render where taskId changes
      // synchronously, outputItems may still hold the previous task's events.
      // Skip processing this frame and wait for the next render with clean data.
      return;
    }

    if (!taskId) return;

    // Only convert events we haven't processed yet
    const newEvents = outputItems.filter((event) => event.seq > lastProcessedSeqRef.current);
    if (newEvents.length === 0) return;

    const newMessages = convertOutputEventsToMessages(newEvents, initialPrompt);
    lastProcessedSeqRef.current = newEvents[newEvents.length - 1].seq;
    if (newMessages.length === 0) {
      return;
    }

    pendingMessagesRef.current.push(...newMessages);
    if (shouldDeferMessageBatch(newMessages)) {
      if (flushTimerRef.current === null) {
        flushTimerRef.current = window.setTimeout(flushPendingMessages, THINKING_STREAM_FLUSH_MS);
      }
      return;
    }

    flushPendingMessages();
  }, [taskId, outputItems, initialPrompt]);

  const allMessages = useMemo(() => {
    const historyMsgs = history || [];
    const streamIds = new Set(streamMessages.map((m) => m.id));
    const dedupedHistory = historyMsgs.filter((m) => !streamIds.has(m.id));
    const sortedMessages = [...dedupedHistory, ...streamMessages].sort(
      (a, b) => a.metadata.sequence - b.metadata.sequence
    );
    return mergeAdjacentThinkingMessages(suppressUserEchoes(sortedMessages));
  }, [history, streamMessages]);

  return { messages: allMessages };
}
