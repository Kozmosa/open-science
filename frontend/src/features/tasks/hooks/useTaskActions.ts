import { useRef, useState } from 'react';
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

type InterruptFlight = {
  taskId: string;
  mapKey: string;
  promise: Promise<void>;
};

type InterruptVariables = {
  taskId: string;
  flight: InterruptFlight;
};

type InterruptResult = {
  result: Awaited<ReturnType<typeof interruptTurn>>;
  taskId: string;
  turnId: string;
  key: string;
  semanticKey: string;
};

type SendPromptVariables = {
  taskId: string;
  prompt: string;
};

type SendPromptResult = {
  result: Awaited<ReturnType<typeof sendTaskPrompt>>;
  taskId: string;
  key: string;
};

function interruptFlightKey(taskId: string, turnId: string | null): string {
  return semanticMutationValue({ taskId, turnId });
}

export function useTaskActions(taskId: string | null) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const t = useT();
  const interruptFlights = useRef(new Map<string, InterruptFlight>()).current;
  const interruptKeyManagers = useRef(new Map<string, IdempotencyKeyManager>()).current;
  const promptKeyManager = useRef(new IdempotencyKeyManager('turn.submit')).current;
  const [pendingInterrupts, setPendingInterrupts] = useState<Record<string, InterruptFlight>>({});

  const invalidateTaskQueries = (requestTaskId: string) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(requestTaskId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(requestTaskId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.turns(requestTaskId) });
  };

  const releaseInterruptFlight = (flight: InterruptFlight) => {
    for (const [mapKey, current] of interruptFlights.entries()) {
      if (current === flight) interruptFlights.delete(mapKey);
    }
    setPendingInterrupts((current) => {
      if (current[flight.taskId] !== flight) return current;
      const next = { ...current };
      delete next[flight.taskId];
      return next;
    });
  };

  const moveInterruptFlight = (flight: InterruptFlight, turnId: string) => {
    for (const [mapKey, current] of interruptFlights.entries()) {
      if (current === flight) interruptFlights.delete(mapKey);
    }
    flight.mapKey = interruptFlightKey(flight.taskId, turnId);
    interruptFlights.set(flight.mapKey, flight);
  };

  const interruptMutation = useMutation<InterruptResult, unknown, InterruptVariables>({
    mutationFn: async ({ taskId: requestTaskId, flight }) => {
      const turns = await getTaskTurns(requestTaskId);
      const active = turns.items.find((turn) => turn.status === 'in_progress');
      if (!active) throw new Error('Task has no active Turn');

      const semanticKey = semanticMutationValue({ taskId: requestTaskId, turnId: active.turn_id });
      const keyManager = interruptKeyManagers.get(semanticKey)
        ?? new IdempotencyKeyManager('turn.interrupt');
      interruptKeyManagers.set(semanticKey, keyManager);
      const key = keyManager.keyFor(semanticKey);
      moveInterruptFlight(flight, active.turn_id);
      const result = await interruptTurn(requestTaskId, active.turn_id, key);
      return { result, taskId: requestTaskId, turnId: active.turn_id, key, semanticKey };
    },
    onSuccess: ({ taskId: requestTaskId, key, semanticKey }) => {
      interruptKeyManagers.get(semanticKey)?.markSucceeded(key);
      interruptKeyManagers.delete(semanticKey);
      invalidateTaskQueries(requestTaskId);
    },
    onError: (error, variables) => {
      if (!variables) return;
      showToast(t('pages.tasks.actions.interruptFailed', {
        error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')),
      }), 'error');
    },
    onSettled: (_result, _error, variables) => {
      if (variables) releaseInterruptFlight(variables.flight);
    },
  });

  const sendPromptMutation = useMutation<SendPromptResult, unknown, SendPromptVariables>({
    mutationFn: async ({ taskId: requestTaskId, prompt }) => {
      const key = promptKeyManager.keyFor(semanticMutationValue({ taskId: requestTaskId, prompt }));
      const result = await sendTaskPrompt(requestTaskId, prompt, key);
      return { result, taskId: requestTaskId, key };
    },
    onSuccess: ({ taskId: requestTaskId, key }) => {
      promptKeyManager.markSucceeded(key);
      invalidateTaskQueries(requestTaskId);
    },
    onError: (error, variables) => {
      if (!variables) return;
      showToast(t('pages.tasks.actions.sendPromptFailed', {
        error: getErrorMessage(error, t('pages.tasks.actions.unexpectedError')),
      }), 'error');
    },
  });

  const interrupt = () => {
    const requestTaskId = taskId;
    if (!requestTaskId) return undefined;

    const existing = Array.from(interruptFlights.values())
      .find((flight) => flight.taskId === requestTaskId);
    if (existing) return existing.promise;

    const flight: InterruptFlight = {
      taskId: requestTaskId,
      mapKey: interruptFlightKey(requestTaskId, null),
      promise: Promise.resolve(),
    };
    interruptFlights.set(flight.mapKey, flight);
    setPendingInterrupts((current) => ({ ...current, [requestTaskId]: flight }));
    const promise = interruptMutation.mutateAsync({ taskId: requestTaskId, flight })
      .then(() => undefined, () => undefined)
      .finally(() => releaseInterruptFlight(flight));
    flight.promise = promise;
    return promise;
  };

  const sendPrompt = (prompt: string) => {
    const requestTaskId = taskId;
    if (!requestTaskId) return Promise.reject(new Error(t('pages.tasks.actions.noTaskSelected')));
    return sendPromptMutation.mutateAsync({ taskId: requestTaskId, prompt });
  };

  const isInterruptPending = taskId !== null && pendingInterrupts[taskId] !== undefined;
  const isPromptPending = sendPromptMutation.isPending
    && sendPromptMutation.variables?.taskId === taskId;

  return {
    interrupt,
    sendPrompt,
    isInterruptPending,
    isPending: isInterruptPending || isPromptPending,
  };
}
