import { useCallback, useEffect, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import type { MessageItem } from '../../types';

interface MessageListProps {
  messages: MessageItem[];
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
}

export default function MessageList({ messages, hasMore, loadMore, isLoadingMore }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(true);
  const lastFirstIdRef = useRef<string | null>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);

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
    const firstId = messages.length > 0 ? messages[0].id : null;
    if (firstId !== lastFirstIdRef.current) {
      lastFirstIdRef.current = firstId;
      shouldScrollRef.current = false;
    }

    if (shouldScrollRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView?.({ behavior: 'auto' });
    }
  }, [messages]);

  useEffect(() => {
    const sentinel = topSentinelRef.current;
    if (!sentinel || !hasMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMore && !isLoadingMore) {
          loadMore();
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, isLoadingMore, loadMore]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--text-tertiary)]">
        no messages
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex min-h-0 flex-1 flex-col overflow-auto px-4 py-2"
    >
      {hasMore && (
        <div ref={topSentinelRef} className="flex justify-center py-2">
          <span className="font-mono text-xs text-[var(--text-tertiary)]">
            {isLoadingMore ? 'loading…' : '↑'}
          </span>
        </div>
      )}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
