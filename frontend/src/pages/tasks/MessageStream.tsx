import { useRef, useEffect, useCallback } from 'react';
import type { MessageItem } from '../../types';
import { MessageBlock, CollapsedGroupBlock } from './MessageBlocks';
import { useMessageGroups } from './useMessageGroups';

interface Props {
  messages: MessageItem[];
}

export default function MessageStream({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(true);
  const { displayItems, toggleGroup } = useMessageGroups(messages);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 80;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldScrollRef.current = distanceFromBottom < threshold;
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  useEffect(() => {
    if (shouldScrollRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView?.({ behavior: 'auto' });
    }
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        No messages yet
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-auto px-4 py-2">
      {displayItems.map((item) => {
        if (item.kind === 'group') {
          return (
            <CollapsedGroupBlock
              key={item.id}
              item={item}
              onToggle={() => toggleGroup(item.id)}
            />
          );
        }
        return <MessageBlock key={item.message.id} message={item.message} />;
      })}
      <div ref={bottomRef} />
    </div>
  );
}
