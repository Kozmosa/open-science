import { useMemo, useState, useCallback, useEffect } from 'react';
import type { MessageItem, DisplayMessageItem } from '../../types';

const NON_CHAT_TYPES = new Set(['system_event', 'thinking', 'tool_call', 'tool_result']);

function isNonChat(msg: MessageItem): boolean {
  return NON_CHAT_TYPES.has(msg.type);
}

function groupMessages(messages: MessageItem[]): DisplayMessageItem[] {
  const result: DisplayMessageItem[] = [];
  let i = 0;

  while (i < messages.length) {
    if (!isNonChat(messages[i])) {
      result.push({ kind: 'single', message: messages[i] });
      i++;
      continue;
    }

    const groupStart = i;
    while (i < messages.length && isNonChat(messages[i])) i++;
    const groupMessages = messages.slice(groupStart, i);

    if (groupMessages.length >= 2) {
      result.push({
        kind: 'group',
        id: `group-${groupMessages[0].id}`,
        messages: groupMessages,
        collapsed: true,
      });
    } else {
      result.push({ kind: 'single', message: groupMessages[0] });
    }
  }

  return result;
}

export function useMessageGroups(messages: MessageItem[]) {
  const grouped = useMemo(() => groupMessages(messages), [messages]);

  const [collapsedState, setCollapsedState] = useState<Set<string>>(() => {
    return new Set(grouped.filter((g): g is Extract<typeof g, { kind: 'group' }> => g.kind === 'group').map(g => g.id));
  });

  useEffect(() => {
    setCollapsedState(prev => {
      const currentGroupIds = new Set(
        grouped.filter((g): g is Extract<typeof g, { kind: 'group' }> => g.kind === 'group').map(g => g.id)
      );
      const next = new Set<string>();
      let changed = false;
      for (const id of currentGroupIds) {
        if (prev.has(id)) {
          next.add(id);
        } else {
          next.add(id);
          changed = true;
        }
      }
      if (next.size !== prev.size) {
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [grouped]);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedState(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  const displayItems: DisplayMessageItem[] = useMemo(() => {
    return grouped.map(item => {
      if (item.kind === 'group') {
        return { ...item, collapsed: collapsedState.has(item.id) };
      }
      return item;
    });
  }, [grouped, collapsedState]);

  return { displayItems, toggleGroup };
}
