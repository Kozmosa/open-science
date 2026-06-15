import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseTask, resumeTask, sendTaskPrompt } from '@/shared/api';
import { useToast } from '@/components/common/Toast';
import { useT } from '@/shared/i18n';

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return fallback;
}

export function useTaskActions(taskId: string | null) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const t = useT();

  const pause = useMutation({
    mutationFn: () => pauseTask(taskId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      queryClient.invalidateQueries({ queryKey: ['task-messages', taskId] });
    },
    onError: (error) => {
      showToast(t('pages.tasks.actions.pauseFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
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
      showToast(t('pages.tasks.actions.resumeFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
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
      showToast(t('pages.tasks.actions.sendPromptFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
    },
  });

  return {
    pause: () => taskId && pause.mutate(),
    resume: () => taskId && resume.mutate(),
    sendPrompt: (prompt: string) => {
      if (!taskId) return Promise.reject(new Error(t('pages.tasks.actions.noTaskSelected')));
      return sendPrompt.mutateAsync(prompt);
    },
    isPending: pause.isPending || resume.isPending || sendPrompt.isPending,
  };
}
