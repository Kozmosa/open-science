import { useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getTaskTurns, interruptTurn, sendTaskPrompt } from '../api';
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
  const interruptKeyManager = useRef(new IdempotencyKeyManager('turn.interrupt')).current;
  const promptKeyManager = useRef(new IdempotencyKeyManager('turn.submit')).current;

  const interrupt = useMutation({
    mutationFn: async () => {
      const turns = await getTaskTurns(taskId!);
      const active = turns.items.find((turn) => turn.status === 'in_progress');
      if (!active) throw new Error('Task has no active Turn');
      const key = interruptKeyManager.keyFor(semanticMutationValue({ taskId, turnId: active.turn_id }));
      return { result: await interruptTurn(taskId!, active.turn_id, key), key };
    },
    onSuccess: ({ key }) => {
      interruptKeyManager.markSucceeded(key);
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
    },
    onError: (error) => {
      showToast(t('pages.tasks.actions.interruptFailed', { error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')) }), 'error');
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
    interrupt: () => taskId && interrupt.mutate(),
    sendPrompt: (prompt: string) => {
      if (!taskId) return Promise.reject(new Error(t('pages.tasks.actions.noTaskSelected')));
      return sendPrompt.mutateAsync(prompt);
    },
    isPending: interrupt.isPending || sendPrompt.isPending,
  };
}
