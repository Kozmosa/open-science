import { useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { pauseTask, resumeTask, sendTaskPrompt } from '@/shared/api';
import { useToast } from '@design-system';
import { useT } from '@/shared/i18n';
import { queryKeys } from '@/shared/api/queryKeys';
import { IdempotencyKeyManager, semanticMutationValue } from '@/shared/api/idempotency';

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return fallback;
}

export function useTaskActions(taskId: string | null) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const t = useT();
  const pauseKeyManager = useRef(new IdempotencyKeyManager('task.pause')).current;
  const resumeKeyManager = useRef(new IdempotencyKeyManager('task.resume')).current;
  const promptKeyManager = useRef(new IdempotencyKeyManager('task.continue')).current;

  const pause = useMutation({
    mutationFn: async () => {
      const key = pauseKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await pauseTask(taskId!, key), key };
    },
    onSuccess: ({ key }) => {
      pauseKeyManager.markSucceeded(key);
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
    },
    onError: (error) => {
      showToast(t('pages.tasks.actions.pauseFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
    },
  });

  const resume = useMutation({
    mutationFn: async () => {
      const key = resumeKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await resumeTask(taskId!, key), key };
    },
    onSuccess: ({ key }) => {
      resumeKeyManager.markSucceeded(key);
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
    },
    onError: (error) => {
      showToast(t('pages.tasks.actions.resumeFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
    },
  });

  const sendPrompt = useMutation({
    mutationFn: async (prompt: string) => {
      const key = promptKeyManager.keyFor(semanticMutationValue({ taskId, prompt }));
      return { result: await sendTaskPrompt(taskId!, prompt, key), key };
    },
    onSuccess: ({ key }) => {
      promptKeyManager.markSucceeded(key);
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
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
