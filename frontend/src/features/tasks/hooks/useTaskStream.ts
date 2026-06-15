import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { buildTaskStreamUrl, getTaskOutput } from '@/shared/api';
import { useT } from '@/shared/i18n';
import type { TaskOutputEvent } from '@/shared/types';
import { getNextOutputSeq, mergeOutputItems } from '../utils/output';
import { queryKeys } from '@/shared/api/queryKeys';

const PAGE_SIZE = 10;
const MAX_RENDER_ITEMS = 200;
const RECONNECT_DELAY_MS = 1000;

function shouldRefreshTaskMetadata(item: TaskOutputEvent): boolean {
  if (item.kind !== 'lifecycle') return false;
  try {
    const parsed = JSON.parse(item.content) as unknown;
    if (!parsed || typeof parsed !== 'object') return true;
    const event = parsed as Record<string, unknown>;
    if (event.event_type === 'status') return true;
    if (event.event_type !== 'system') return typeof event.event_type !== 'string';
    const payload = event.payload;
    if (!payload || typeof payload !== 'object') return true;
    const subtype = (payload as Record<string, unknown>).subtype;
    return typeof subtype === 'string' && ['task_paused', 'task_completed', 'task_failed'].includes(subtype);
  } catch {
    return true;
  }
}

function trimOutputItems(items: TaskOutputEvent[]): TaskOutputEvent[] {
  return items.length > MAX_RENDER_ITEMS ? items.slice(items.length - MAX_RENDER_ITEMS) : items;
}

export interface TaskOutputStreamState {
  outputItems: TaskOutputEvent[];
  outputError: string | null;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
}

export function useTaskStream(taskId: string | null): TaskOutputStreamState {
  const queryClient = useQueryClient();
  const t = useT();
  const [outputItems, setOutputItems] = useState<TaskOutputEvent[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const nextSeqRef = useRef<number>(0);
  const loadMoreSeqRef = useRef<number>(0);
  const activeRef = useRef(true);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const appendOutput = useCallback((items: TaskOutputEvent[]) => {
    if (items.length === 0) return;
    setOutputItems((current) => {
      const merged = mergeOutputItems(current, items);
      return trimOutputItems(merged);
    });
    nextSeqRef.current = Math.max(nextSeqRef.current, getNextOutputSeq(items, nextSeqRef.current));
  }, []);

  const loadMore = useCallback(() => {
    if (!taskId || isLoadingMore || !hasMore) return;
    setIsLoadingMore(true);
    const capturedTaskId = taskId;
    const seq = loadMoreSeqRef.current;
    void getTaskOutput(capturedTaskId, seq, PAGE_SIZE)
      .then((page) => {
        if (!activeRef.current || capturedTaskId !== taskId) return;
        if (page.items.length > 0) {
          setOutputItems((current) => trimOutputItems(mergeOutputItems(current, page.items)));
          loadMoreSeqRef.current = page.items[page.items.length - 1].seq;
        }
        setHasMore(page.has_more);
      })
      .catch(() => {
        // silent — user can retry by scrolling up again
      })
      .finally(() => setIsLoadingMore(false));
  }, [taskId, isLoadingMore, hasMore]);

  useEffect(() => {
    activeRef.current = true;
    const closeCurrentStream = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    closeCurrentStream();
    setOutputItems([]);
    setOutputError(null);
    setHasMore(false);
    setIsLoadingMore(false);
    nextSeqRef.current = 0;
    loadMoreSeqRef.current = 0;

    if (taskId === null) {
      return () => {
        activeRef.current = false;
        closeCurrentStream();
      };
    }

    let refillPromise: Promise<void> | null = null;

    const refillGap = async (): Promise<void> => {
      if (refillPromise) return refillPromise;
      refillPromise = (async () => {
        try {
          const page = await getTaskOutput(taskId, nextSeqRef.current);
          if (!activeRef.current) return;
          appendOutput(page.items);
        } catch (error) {
          if (activeRef.current) {
            setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.replayFailed'));
          }
        } finally {
          refillPromise = null;
        }
      })();
      return refillPromise;
    };

    const openStream = () => {
      closeCurrentStream();
      const source = new EventSource(buildTaskStreamUrl(taskId, nextSeqRef.current));
      eventSourceRef.current = source;

      source.onmessage = (event: MessageEvent<string>) => {
        if (!activeRef.current) return;
        try {
          const item = JSON.parse(event.data) as TaskOutputEvent;
          if (item.task_id !== taskId) return;
          if (item.seq > nextSeqRef.current + 1) {
            void refillGap();
          }
          if (item.seq > nextSeqRef.current) {
            appendOutput([item]);
          }
          if (shouldRefreshTaskMetadata(item)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
            void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
          }
        } catch (error) {
          if (activeRef.current) {
            setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.parseFailed'));
          }
        }
      };

      source.onerror = () => {
        source.close();
        if (!activeRef.current) return;
        void refillGap().finally(() => {
          if (!activeRef.current) return;
          reconnectTimerRef.current = setTimeout(openStream, RECONNECT_DELAY_MS);
        });
      };
    };

    void (async () => {
      try {
        const page = await getTaskOutput(taskId, 0, PAGE_SIZE);
        if (!activeRef.current) return;
        if (page.items.length > 0) {
          const trimmed = trimOutputItems(page.items);
          setOutputItems(trimmed);
          nextSeqRef.current = getNextOutputSeq(trimmed, 0);
          loadMoreSeqRef.current = trimmed[trimmed.length - 1].seq;
        }
        setHasMore(page.has_more);
        openStream();
      } catch (error) {
        if (activeRef.current) {
          setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.loadFailed'));
        }
      }
    })();

    return () => {
      activeRef.current = false;
      closeCurrentStream();
    };
  }, [queryClient, taskId, t, appendOutput]);

  return { outputItems, outputError, hasMore, loadMore, isLoadingMore };
}
