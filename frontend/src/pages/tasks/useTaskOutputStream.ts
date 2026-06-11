import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { buildTaskStreamUrl, getTaskOutput } from '../../api';
import { useT } from '../../i18n';
import type { TaskOutputEvent } from '../../types';
import { getNextOutputSeq, mergeOutputItems, trimStreamingWindow } from './output';

const PAGE_SIZE = 10;
const CACHE_PREFIX = 'ainrf-task-output-';
const taskMetadataSystemSubtypes = new Set(['task_paused', 'task_completed', 'task_failed']);

function shouldRefreshTaskMetadata(item: TaskOutputEvent): boolean {
  if (item.kind !== 'lifecycle') {
    return false;
  }
  try {
    const parsed = JSON.parse(item.content) as unknown;
    if (!parsed || typeof parsed !== 'object') return true;
    const event = parsed as Record<string, unknown>;
    const eventType = event.event_type;
    if (eventType === 'status') return true;
    if (eventType !== 'system') return typeof eventType !== 'string';
    const payload = event.payload;
    if (!payload || typeof payload !== 'object') return true;
    const subtype = (payload as Record<string, unknown>).subtype;
    return typeof subtype === 'string' && taskMetadataSystemSubtypes.has(subtype);
  } catch {
    return true;
  }
}

function readCache(taskId: string): TaskOutputEvent[] | null {
  try {
    const raw = sessionStorage.getItem(`${CACHE_PREFIX}${taskId}`);
    if (!raw) return null;
    return JSON.parse(raw) as TaskOutputEvent[];
  } catch {
    return null;
  }
}

function writeCache(taskId: string, items: TaskOutputEvent[]): void {
  try {
    sessionStorage.setItem(`${CACHE_PREFIX}${taskId}`, JSON.stringify(items));
  } catch {
    // quota exceeded — ignore
  }
}



interface TaskOutputStreamState {
  outputItems: TaskOutputEvent[];
  outputError: string | null;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
}

export function useTaskOutputStream(taskId: string | null): TaskOutputStreamState {
  const queryClient = useQueryClient();
  const t = useT();
  const [outputItems, setOutputItems] = useState<TaskOutputEvent[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const nextSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const refillPromiseRef = useRef<Promise<void> | null>(null);
  const loadMoreSeqRef = useRef<number>(0);

  const writeCacheTimerRef = useRef<number | null>(null);

  const appendOutput = useCallback(
    (items: TaskOutputEvent[], taskId: string) => {
      const taskItems = items.filter((item) => item.task_id === taskId);
      if (taskItems.length === 0) return;
      setOutputItems((current) => {
        const merged = mergeOutputItems(current, taskItems);
        const trimmed = trimStreamingWindow(merged);
        // Debounced cache write: schedule a write in 300ms, cancelling any pending one
        if (writeCacheTimerRef.current !== null) {
          window.clearTimeout(writeCacheTimerRef.current);
        }
        const itemsToCache = trimmed;
        writeCacheTimerRef.current = window.setTimeout(() => {
          writeCacheTimerRef.current = null;
          writeCache(taskId, itemsToCache);
        }, 300);
        return trimmed;
      });
      nextSeqRef.current = Math.max(
        nextSeqRef.current,
        getNextOutputSeq(taskItems, nextSeqRef.current)
      );
    },
    []
  );

  // ── Load more (scroll up) ──────────────────────────────────
  const loadMore = useCallback(() => {
    if (!taskId || isLoadingMore || !hasMore) return;
    setIsLoadingMore(true);
    const seq = loadMoreSeqRef.current;
    void getTaskOutput(taskId, seq, PAGE_SIZE)
      .then((page) => {
        if (page.items.length > 0) {
          setOutputItems((current) => {
            const merged = mergeOutputItems(current, page.items);
            writeCache(taskId, merged);
            return merged;
          });
          // loadMoreSeq moves to the next batch boundary
          loadMoreSeqRef.current = page.items[page.items.length - 1].seq;
        }
        setHasMore(page.has_more);
      })
      .catch(() => {
        // silent — user can retry by scrolling up again
      })
      .finally(() => setIsLoadingMore(false));
  }, [taskId, isLoadingMore, hasMore]);

  // ── Main effect: initial load + SSE stream ─────────────────
  useEffect(() => {
    const closeCurrentStream = (): void => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    closeCurrentStream();
    refillPromiseRef.current = null;
    // Flush any pending debounced cache write from previous task
    if (writeCacheTimerRef.current !== null) {
      window.clearTimeout(writeCacheTimerRef.current);
      writeCacheTimerRef.current = null;
    }
    setOutputItems([]);
    setOutputError(null);
    setHasMore(false);
    setIsLoadingMore(false);
    nextSeqRef.current = 0;
    loadMoreSeqRef.current = 0;

    if (taskId === null) {
      return undefined;
    }

    let active = true;

    const refillGap = async (): Promise<void> => {
      if (refillPromiseRef.current) return refillPromiseRef.current;
      refillPromiseRef.current = (async () => {
        try {
          const page = await getTaskOutput(taskId, nextSeqRef.current);
          if (!active) return;
          appendOutput(page.items, taskId);
        } catch (error) {
          if (active) {
            setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.replayFailed'));
          }
        } finally {
          refillPromiseRef.current = null;
        }
      })();
      return refillPromiseRef.current;
    };

    const openStream = (): void => {
      closeCurrentStream();
      const source = new EventSource(buildTaskStreamUrl(taskId, nextSeqRef.current));
      eventSourceRef.current = source;
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          const item = JSON.parse(event.data) as TaskOutputEvent;
          if (item.task_id !== taskId) return;
          if (item.seq > nextSeqRef.current + 1) void refillGap();
          if (item.seq > nextSeqRef.current) {
            appendOutput([item], taskId);
          }
          if (shouldRefreshTaskMetadata(item)) {
            void queryClient.invalidateQueries({ queryKey: ['tasks'] });
            void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
          }
        } catch (error) {
          setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.parseFailed'));
        }
      };
      source.onerror = () => {
        source.close();
        if (!active) return;
        void refillGap().finally(() => {
          if (!active) return;
          reconnectTimerRef.current = window.setTimeout(openStream, 1000);
        });
      };
    };

    void (async () => {
      try {
        // 1. Try sessionStorage cache first
        const cached = readCache(taskId);
        if (cached && cached.length > 0) {
          const trimmedCache = trimStreamingWindow(cached);
          setOutputItems(trimmedCache);
          const maxCachedSeq = getNextOutputSeq(trimmedCache, 0);
          nextSeqRef.current = maxCachedSeq;
          loadMoreSeqRef.current = maxCachedSeq;
          // Fetch only new items after the cache
          const page = await getTaskOutput(taskId, maxCachedSeq);
          if (!active) return;
          if (page.items.length > 0) {
            appendOutput(page.items, taskId);
          }
          setHasMore(false); // cache means we loaded all history already
        } else {
          // 2. No cache — load first PAGE_SIZE items from the beginning
          const page = await getTaskOutput(taskId, 0, PAGE_SIZE);
          if (!active) return;
          if (page.items.length > 0) {
            const trimmed = trimStreamingWindow(page.items);
            setOutputItems(trimmed);
            writeCache(taskId, trimmed);
            nextSeqRef.current = getNextOutputSeq(trimmed, 0);
            // loadMoreSeq starts at 0 + items loaded = next batch boundary
            loadMoreSeqRef.current = trimmed[trimmed.length - 1].seq;
          }
          setHasMore(page.has_more);
        }
        openStream();
      } catch (error) {
        if (active) {
          setOutputError(error instanceof Error ? error.message : t('pages.tasks.output.loadFailed'));
        }
      }
    })();

    return () => {
      active = false;
      closeCurrentStream();
      // Flush pending cache write on unmount
      if (writeCacheTimerRef.current !== null) {
        window.clearTimeout(writeCacheTimerRef.current);
        writeCacheTimerRef.current = null;
      }
    };
  }, [queryClient, taskId, t, appendOutput]);

  return { outputItems, outputError, hasMore, loadMore, isLoadingMore };
}
