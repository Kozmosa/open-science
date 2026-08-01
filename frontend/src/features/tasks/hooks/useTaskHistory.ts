import { useQuery } from '@tanstack/react-query';
import { listCanonicalTaskItems } from '../api';
import type { TurnItemResponse } from '@/shared/api/transportTypes';
import type { MessageItem } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';

function itemToMessage(item: TurnItemResponse): MessageItem {
  const payload = item.payload ?? {};
  const typeByItem: Record<string, MessageItem['type']> = {
    user_message: 'user',
    agent_message: 'assistant',
    reasoning_summary: 'thinking',
    tool_call: 'tool_call',
    tool_result: 'tool_result',
  };
  const type = typeByItem[item.item_type] ?? 'system_event';
  const text = payload.text ?? payload.content ?? payload.message;
  return {
    id: item.item_id,
    type,
    content: typeof text === 'string' ? text : payload,
    metadata: {
      timestamp: typeof item.persisted_at === 'string' ? item.persisted_at : '',
      sequence: item.task_item_seq,
      isFolded: ['thinking', 'tool_call', 'tool_result'].includes(type),
    },
  };
}

async function fetchAllMessages(taskId: string): Promise<MessageItem[]> {
  return (await listCanonicalTaskItems(taskId)).map(itemToMessage);
}

export function useTaskHistory(taskId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.messages(taskId),
    queryFn: () => fetchAllMessages(taskId!),
    enabled: !!taskId,
    staleTime: 0,
  });
}
