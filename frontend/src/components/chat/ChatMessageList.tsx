import { useCallback, useEffect, useRef, useState } from 'react';
import { useT } from '@/shared/i18n';
import ChatAssistantMessage from './ChatAssistantMessage';
import ChatUserMessage from './ChatUserMessage';
import type { ChatMessage } from './types';

interface ChatMessageListProps {
  messages: ChatMessage[];
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  onRetry?: () => void;
}

export default function ChatMessageList({
  messages,
  hasMore,
  loadMore,
  isLoadingMore,
  onRetry,
}: ChatMessageListProps) {
  const t = useT();
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(true);
  const lastFirstIdRef = useRef<string | null>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 80;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    shouldScrollRef.current = distanceFromBottom < threshold;
    setShowScrollButton(distanceFromBottom >= threshold);
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

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6 font-mono text-xs text-[var(--text-tertiary)]">
        {t('common.noMessages')}
      </div>
    );
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <div
        ref={containerRef}
        className="flex min-h-0 flex-1 flex-col overflow-auto px-4 py-6 pb-32 space-y-8"
      >
        {hasMore && (
          <div ref={topSentinelRef} className="flex justify-center py-2">
            <span className="font-mono text-xs text-[var(--text-tertiary)]">
              {isLoadingMore ? `${t('common.loading')}` : '↑'}
            </span>
          </div>
        )}

        {messages.map((message) => {
          if (message.role === 'user') {
            return <ChatUserMessage key={message.id} message={message} />;
          }
          if (message.role === 'assistant') {
            return <ChatAssistantMessage key={message.id} message={message} onRetry={onRetry} />;
          }
          return (
            <div
              key={message.id}
              className="flex justify-center py-2 text-xs text-[var(--text-tertiary)]"
            >
              {message.content}
            </div>
          );
        })}

        <div ref={bottomRef} />
      </div>

      {showScrollButton && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-36 left-1/2 -translate-x-1/2 bg-[var(--surface)] border border-[var(--border)] w-8 h-8 rounded-full flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--bg-secondary)] shadow-sm transition-all animate-in fade-in slide-in-from-bottom-2 z-20 cursor-pointer"
          aria-label={t('chat.scrollToBottom')}
        >
          <svg
            className="w-4 h-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 5v14M19 12l-7 7-7-7" />
          </svg>
        </button>
      )}
    </div>
  );
}
