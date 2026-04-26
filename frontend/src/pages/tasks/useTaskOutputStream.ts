import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { buildTaskStreamUrl, getTaskOutput } from '../../api';
import type { TaskOutputEvent } from '../../types';
import { getNextOutputSeq, mergeOutputItems } from './output';

interface TaskOutputStreamState {
  outputItems: TaskOutputEvent[];
  outputError: string | null;
}

export function useTaskOutputStream(taskId: string | null): TaskOutputStreamState {
  const queryClient = useQueryClient();
  const [outputItems, setOutputItems] = useState<TaskOutputEvent[]>([]);
  const [outputError, setOutputError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const nextSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (taskId === null) {
      nextSeqRef.current = 0;
      return undefined;
    }

    let active = true;

    const closeStream = (): void => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const updateNextSeq = (seq: number): void => {
      nextSeqRef.current = Math.max(nextSeqRef.current, seq);
    };

    const appendOutput = (items: TaskOutputEvent[]): void => {
      setOutputItems((current) => mergeOutputItems(current, items));
      updateNextSeq(getNextOutputSeq(items, nextSeqRef.current));
    };

    const refillGap = async (): Promise<void> => {
      try {
        const page = await getTaskOutput(taskId, nextSeqRef.current);
        if (!active) {
          return;
        }
        appendOutput(page.items);
        updateNextSeq(page.next_seq);
      } catch (error) {
        if (active) {
          setOutputError(error instanceof Error ? error.message : 'Unable to replay task output');
        }
      }
    };

    const openStream = (): void => {
      closeStream();
      const source = new EventSource(buildTaskStreamUrl(taskId, nextSeqRef.current));
      eventSourceRef.current = source;
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          const item = JSON.parse(event.data) as TaskOutputEvent;
          if (item.seq > nextSeqRef.current + 1) {
            void refillGap();
          }
          if (item.seq > nextSeqRef.current) {
            appendOutput([item]);
          }
          if (item.kind === 'lifecycle') {
            void queryClient.invalidateQueries({ queryKey: ['tasks'] });
            void queryClient.invalidateQueries({ queryKey: ['task', taskId] });
          }
        } catch (error) {
          setOutputError(error instanceof Error ? error.message : 'Unable to parse task output');
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
        setOutputItems([]);
        setOutputError(null);
        nextSeqRef.current = 0;
        const page = await getTaskOutput(taskId, 0);
        if (!active) {
          return;
        }
        setOutputItems(page.items);
        nextSeqRef.current = getNextOutputSeq(page.items, page.next_seq);
        openStream();
      } catch (error) {
        if (active) {
          setOutputError(error instanceof Error ? error.message : 'Unable to load task output');
        }
      }
    })();

    return () => {
      active = false;
      closeStream();
    };
  }, [queryClient, taskId]);

  return { outputItems, outputError };
}
