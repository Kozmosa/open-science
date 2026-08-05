import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { TaskOutputEvent } from '../types';
import { queryKeys } from '@/shared/api/queryKeys';

export interface TaskOutputStreamState {
  outputItems: TaskOutputEvent[];
  outputError: string | null;
  hasMore: boolean;
  loadMore: () => void;
  isLoadingMore: boolean;
  connectionState: 'idle' | 'connecting' | 'connected' | 'disconnected';
}

export function useTaskStream(
  taskId: string | null,
  onConnectionStateChange?: (state: TaskOutputStreamState['connectionState']) => void,
): TaskOutputStreamState {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!taskId) {
      onConnectionStateChange?.('idle');
      return;
    }
    onConnectionStateChange?.('connected');
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    };
    refresh();
    const interval = window.setInterval(refresh, 1000);
    return () => window.clearInterval(interval);
  }, [onConnectionStateChange, queryClient, taskId]);

  return {
    outputItems: [],
    outputError: null,
    hasMore: false,
    loadMore: () => undefined,
    isLoadingMore: false,
    connectionState: taskId ? 'connected' : 'idle',
  };
}
