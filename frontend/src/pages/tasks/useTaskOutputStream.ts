import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { buildTaskStreamUrl, getTaskOutput } from '../../api';
import { useT } from '../../i18n';
import type { TaskOutputEvent } from '../../types';
import { getNextOutputSeq, mergeOutputItems } from './output';

const maxOutputItems = 500;
const taskMetadataSystemSubtypes = new Set(['task_paused', 'task_completed', 'task_failed']);

function shouldRefreshTaskMetadata(item: TaskOutputEvent): boolean {
  if (item.kind !== 'lifecycle') {
    return false;
  }

  try {
    const parsed = JSON.parse(item.content) as unknown;
    if (!parsed || typeof parsed !== 'object') {
      return true;
    }
    const event = parsed as Record<string, unknown>;
    const eventType = event.event_type;
    if (eventType === 'status') {
      return true;
    }
    if (eventType !== 'system') {
      return typeof eventType !== 'string';
    }
    const payload = event.payload;
    if (!payload || typeof payload !== 'object') {
      return true;
    }
    const subtype = (payload as Record<string, unknown>).subtype;
    return typeof subtype === 'string' && taskMetadataSystemSubtypes.has(subtype);
  } catch {
    return true;
  }
}


interface TaskOutputStreamState {
  outputItems: TaskOutputEvent[];
  outputError: string | null;
}

export function useTaskOutputStream(taskId: string | null): TaskOutputStreamState {
  const queryClient = useQueryClient();
  const t = useT();
  const [outputItems, setOutputItems] = useState<TaskOutputEvent[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const nextSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const refillPromiseRef = useRef<Promise<void> | null>(null);

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
    setOutputItems([]);
    setOutputError(null);
    nextSeqRef.current = 0;

    if (taskId === null) {
      return undefined;
    }

    let active = true;

    const updateNextSeq = (seq: number): void => {
      nextSeqRef.current = Math.max(nextSeqRef.current, seq);
    };

    const appendOutput = (items: TaskOutputEvent[]): void => {
      const taskItems = items.filter((item) => item.task_id === taskId);
      if (taskItems.length === 0) {
        return;
      }
      setOutputItems((current) => mergeOutputItems(current, taskItems).slice(-maxOutputItems));
      updateNextSeq(getNextOutputSeq(taskItems, nextSeqRef.current));
    };

    const refillGap = async (): Promise<void> => {
      if (refillPromiseRef.current) {
        return refillPromiseRef.current;
      }

      refillPromiseRef.current = (async () => {
        try {
          const page = await getTaskOutput(taskId, nextSeqRef.current);
          if (!active) {
            return;
          }
          appendOutput(page.items);
          updateNextSeq(page.next_seq);
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
          if (item.task_id !== taskId) {
            return;
          }
          if (item.seq > nextSeqRef.current + 1) {
            void refillGap();
          }
          if (item.seq > nextSeqRef.current) {
            appendOutput([item]);
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
        if (!active) {
          return;
        }
        void refillGap().finally(() => {
          if (!active) {
            return;
          }
          reconnectTimerRef.current = window.setTimeout(openStream, 1000);
        });
      };
    };

    void (async () => {
      try {
        const page = await getTaskOutput(taskId, 0);
        if (!active) {
          return;
        }
        appendOutput(page.items);
        nextSeqRef.current = getNextOutputSeq(
          page.items.filter((item) => item.task_id === taskId),
          page.next_seq
        );
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
    };
  }, [queryClient, taskId, t]);

  return { outputItems, outputError };
}
