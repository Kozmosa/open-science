import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseTask, resumeTask, sendTaskPrompt } from '../../api';
import { useToast } from '../../components/common/Toast';

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'An unexpected error occurred';
}

export function useTaskActions(taskId: string | null) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const pause = useMutation({
    mutationFn: () => pauseTask(taskId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task-messages', taskId] });
    },
    onError: (error) => {
      showToast(`Pause failed: ${getErrorMessage(error)}`, 'error');
    },
  });

  const resume = useMutation({
    mutationFn: () => resumeTask(taskId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task-messages', taskId] });
    },
    onError: (error) => {
      showToast(`Resume failed: ${getErrorMessage(error)}`, 'error');
    },
  });

  const sendPrompt = useMutation({
    mutationFn: (prompt: string) => sendTaskPrompt(taskId!, prompt),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task-messages', taskId] });
    },
    onError: (error) => {
      showToast(`Send prompt failed: ${getErrorMessage(error)}`, 'error');
    },
  });

  return {
    pause: () => taskId && pause.mutate(),
    resume: () => taskId && resume.mutate(),
    sendPrompt: (prompt: string) => {
      if (!taskId) return Promise.reject(new Error('No task selected'));
      return sendPrompt.mutateAsync(prompt);
    },
    isPending: pause.isPending || resume.isPending || sendPrompt.isPending,
  };
}
