import { useQuery } from '@tanstack/react-query';
import { getTaskMessages } from '@/shared/api';
import type { MessageItem } from '@/shared/types';

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

export function useTaskHistory(taskId: string | null) {
  return useQuery({
    queryKey: ['task-messages', taskId],
    queryFn: () => fetchAllMessages(taskId!),
    enabled: !!taskId,
    staleTime: 0,
  });
}
