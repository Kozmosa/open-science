import { useRef, useEffect, useCallback } from 'react';
import type { MessageItem } from '../../types';
import { MessageBlock, CollapsedGroupBlock } from './MessageBlocks';
import { useT } from '../../i18n';
import { useMessageGroups } from './useMessageGroups';

interface Props {
  messages: MessageItem[];
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
}

export default function MessageStream({ messages, hasMore, loadMore, isLoadingMore }: Props) {
  const t = useT();
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(false);
  const lastFirstIdRef = useRef<string | null>(null);
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
    const firstId = messages.length > 0 ? messages[0].id : null;
    if (firstId !== lastFirstIdRef.current) {
      lastFirstIdRef.current = firstId;
      shouldScrollRef.current = false;
    }

    if (shouldScrollRef.current && bottomRef.current) {
      bottomRef.current.scrollIntoView?.({ behavior: 'auto' });
    }
  }, [messages]);

  // ── IntersectionObserver for load-more sentinel at top ──────
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
      <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
        {t('common.noMessages')}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 flex-col overflow-auto px-4 py-2">
      {/* Sentinel for load-more at the top */}
      {hasMore && (
        <div ref={topSentinelRef} className="flex justify-center py-2">
          <span className="text-xs text-[var(--text-tertiary)]">
            {isLoadingMore ? t('common.loading') : '↑'}
          </span>
        </div>
      )}
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
