import type { ChatMessage, ChatToolCallData, MessageItem, ToolCallStatus } from './types';

function canJoinComposite(type: MessageItem['type'], sourceKind?: string): boolean {
  if (type === 'thinking' || type === 'tool_call' || type === 'tool_result') return true;
  if (type === 'assistant' && sourceKind === 'message') return true;
  return false;
}

function shouldRenderStandalone(type: MessageItem['type'], sourceKind?: string): boolean {
  return type === 'assistant' && sourceKind !== 'message';
}

function stringifyArgs(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function detectError(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === 'object') {
    const keys = Object.keys(value);
    if (keys.includes('error') || keys.includes('failure')) return true;
  }
  const text = typeof value === 'string' ? value.toLowerCase() : JSON.stringify(value).toLowerCase();
  return text.includes('"error"') || text.includes('exception') || text.startsWith('error:');
}

function toolStatus(hasResult: boolean, resultValue: unknown): ToolCallStatus {
  if (!hasResult) return 'running';
  return detectError(resultValue) ? 'error' : 'success';
}

interface MutableAssistantGroup {
  id: string;
  sequence: number;
  timestamp: string;
  content: string;
  thinking: string;
  toolCalls: ChatToolCallData[];
  toolCallIndexById: Map<string, number>;
  isStreaming: boolean;
}

function createAssistantGroup(message: MessageItem): MutableAssistantGroup {
  return {
    id: message.id,
    sequence: message.metadata.sequence,
    timestamp: message.metadata.timestamp,
    content: '',
    thinking: '',
    toolCalls: [],
    toolCallIndexById: new Map(),
    isStreaming: message.metadata.isStreaming ?? false,
  };
}

function appendAssistantMessage(group: MutableAssistantGroup, message: MessageItem): void {
  group.isStreaming = group.isStreaming || (message.metadata.isStreaming ?? false);
  group.timestamp = message.metadata.timestamp;

  if (message.type === 'thinking') {
    const text = typeof message.content === 'string' ? message.content : stringifyArgs(message.content);
    group.thinking = group.thinking ? `${group.thinking}\n${text}` : text;
    return;
  }

  if (message.type === 'assistant') {
    const text = typeof message.content === 'string' ? message.content : stringifyArgs(message.content);
    group.content = group.content ? `${group.content}${text}` : text;
    return;
  }

  if (message.type === 'tool_call') {
    const payload = typeof message.content === 'object' && message.content !== null
      ? (message.content as Record<string, unknown>)
      : {};
    const id = typeof payload.id === 'string' ? payload.id : `tc-${message.metadata.sequence}`;
    const name = String(payload.name ?? 'unknown');
    const args = stringifyArgs(payload.arguments ?? payload.args ?? {});

    const existingIndex = group.toolCallIndexById.get(id);
    if (existingIndex !== undefined) {
      // Update an in-place tool call if it somehow repeats (defensive).
      group.toolCalls[existingIndex] = { ...group.toolCalls[existingIndex], name, args };
    } else {
      group.toolCalls.push({ id, name, args, status: 'running' });
      group.toolCallIndexById.set(id, group.toolCalls.length - 1);
    }
    return;
  }

  if (message.type === 'tool_result') {
    const payload = typeof message.content === 'object' && message.content !== null
      ? (message.content as Record<string, unknown>)
      : {};
    const toolUseId = typeof payload.tool_use_id === 'string' ? payload.tool_use_id : null;
    const result = stringifyArgs(payload.content ?? payload.result ?? payload.output ?? '');

    if (toolUseId) {
      const index = group.toolCallIndexById.get(toolUseId);
      if (index !== undefined) {
        const existing = group.toolCalls[index];
        group.toolCalls[index] = { ...existing, result, status: toolStatus(true, payload.content) };
        return;
      }
    }

    // Fallback: pair with the first running tool call in order.
    const pendingIndex = group.toolCalls.findIndex((tc) => tc.status === 'running');
    if (pendingIndex !== -1) {
      const existing = group.toolCalls[pendingIndex];
      group.toolCalls[pendingIndex] = {
        ...existing,
        result,
        status: toolStatus(true, payload.content),
      };
      if (toolUseId) {
        group.toolCallIndexById.set(toolUseId, pendingIndex);
      }
    } else {
      // Orphan result: render as a standalone running→success entry.
      const id = toolUseId ?? `tr-${message.metadata.sequence}`;
      group.toolCalls.push({
        id,
        name: 'tool result',
        args: '',
        result,
        status: toolStatus(true, payload.content),
      });
    }
  }
}

function finalizeAssistantGroup(group: MutableAssistantGroup): ChatMessage {
  const hasAnyOutput = !!(group.content || group.thinking || group.toolCalls.length > 0);
  const aborted = !group.isStreaming && !group.content && hasAnyOutput;

  // When streaming ends, resolve any tool calls that are still marked as
  // running. This prevents the spinner from animating indefinitely after a
  // task has completed but some tool_result events never arrived (e.g. agent
  // terminated mid-call, or orphan tool calls without matching results).
  const resolvedToolCalls = group.isStreaming
    ? group.toolCalls
    : group.toolCalls.map((tc) =>
        tc.status === 'running' ? { ...tc, status: 'success' as ToolCallStatus } : tc,
      );

  return {
    id: group.id,
    role: 'assistant',
    sequence: group.sequence,
    timestamp: group.timestamp,
    content: group.content || undefined,
    thinking: group.thinking || undefined,
    toolCalls: resolvedToolCalls.length > 0 ? resolvedToolCalls : undefined,
    isStreaming: group.isStreaming,
    aborted,
  };
}

/**
 * Convert the flat MessageItem stream emitted by the backend into grouped
 * chat messages suitable for a conversation UI.
 *
 * Flat events for a single assistant turn (thinking → tool_calls →
 * tool_results → assistant content) are merged into one assistant message.
 */
export function groupMessages(messages: MessageItem[]): ChatMessage[] {
  const sorted = [...messages].sort((a, b) => a.metadata.sequence - b.metadata.sequence);
  const result: ChatMessage[] = [];
  let currentGroup: MutableAssistantGroup | null = null;

  const flushGroup = () => {
    if (!currentGroup) return;
    result.push(finalizeAssistantGroup(currentGroup));
    currentGroup = null;
  };

  for (const message of sorted) {
    if (message.type === 'user') {
      flushGroup();
      const content = typeof message.content === 'string' ? message.content : stringifyArgs(message.content);
      result.push({
        id: message.id,
        role: 'user',
        sequence: message.metadata.sequence,
        timestamp: message.metadata.timestamp,
        content,
      });
      continue;
    }

    if (message.type === 'system_event') {
      flushGroup();
      const content = typeof message.content === 'string' ? message.content : stringifyArgs(message.content);
      result.push({
        id: message.id,
        role: 'system',
        sequence: message.metadata.sequence,
        timestamp: message.metadata.timestamp,
        content,
      });
      continue;
    }

    if (shouldRenderStandalone(message.type, message.metadata.sourceKind)) {
      flushGroup();
      const content = typeof message.content === 'string' ? message.content : stringifyArgs(message.content);
      result.push({
        id: message.id,
        role: 'assistant',
        sequence: message.metadata.sequence,
        timestamp: message.metadata.timestamp,
        content,
        isStreaming: message.metadata.isStreaming ?? false,
        aborted: false,
      });
      continue;
    }

    if (!canJoinComposite(message.type, message.metadata.sourceKind)) {
      continue;
    }

    if (!currentGroup) {
      currentGroup = createAssistantGroup(message);
    } else if (
      currentGroup.content &&
      (message.type === 'thinking' || message.type === 'tool_call')
    ) {
      // A new reasoning burst after content suggests a fresh assistant turn.
      flushGroup();
      currentGroup = createAssistantGroup(message);
    }

    appendAssistantMessage(currentGroup, message);
  }

  flushGroup();
  return result;
}
