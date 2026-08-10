import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/shared/i18n';
import { ToastProvider } from '@design-system';
import { createTestQueryClient } from '@/test-support/render';
import { queryKeys } from '@/shared/api/queryKeys';
import { useTaskActions } from '@features/tasks/hooks/useTaskActions';
import { getTaskTurns, interruptTurn, sendTaskPrompt } from '@features/tasks/api';
import type { TaskTurnListResponse } from '@features/tasks/types';

vi.mock('@features/tasks/api', () => ({
  getTaskTurns: vi.fn(),
  interruptTurn: vi.fn(),
  sendTaskPrompt: vi.fn(),
}));

const mockGetTaskTurns = vi.mocked(getTaskTurns);
const mockInterruptTurn = vi.mocked(interruptTurn);
const mockSendTaskPrompt = vi.mocked(sendTaskPrompt);

function activeTurn(taskId: string, turnId: string): TaskTurnListResponse {
  return {
    items: [{
      task_id: taskId,
      turn_id: turnId,
      turn_seq: 1,
      status: 'in_progress',
      started_at: null,
      finished_at: null,
      failure_code: null,
      token_usage_json: null,
      context_snapshot_ref: null,
    }],
  };
}

function wrapperFor(client: ReturnType<typeof createTestQueryClient>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <LocaleProvider initialLocale="en">
        <QueryClientProvider client={client}>
          <ToastProvider>{children}</ToastProvider>
        </QueryClientProvider>
      </LocaleProvider>
    );
  };
}

beforeEach(() => {
  mockGetTaskTurns.mockReset();
  mockInterruptTurn.mockReset();
  mockSendTaskPrompt.mockReset();
  mockInterruptTurn.mockResolvedValue({
    control_request_id: 'control-1',
    expected_turn_id: 'turn-a',
    kind: 'interrupt',
    status: 'accepted',
    task_id: 'task-a',
  });
  mockSendTaskPrompt.mockResolvedValue({
    submission_id: 'submission-1',
    task_id: 'task-a',
    reserved_turn_id: 'turn-a',
    status: 'queued',
    disposition: 'queued',
  });
});

describe('useTaskActions interrupt ownership', () => {
  it('latches same-tick duplicate interrupts before the Turn lookup resolves', async () => {
    let resolveTurns: ((value: TaskTurnListResponse) => void) | undefined;
    mockGetTaskTurns.mockImplementation(() => new Promise((resolve) => {
      resolveTurns = resolve;
    }));
    const client = createTestQueryClient();
    const { result } = renderHook(() => useTaskActions('task-a'), { wrapper: wrapperFor(client) });

    let first: Promise<void> | undefined;
    let second: Promise<void> | undefined;
    act(() => {
      first = result.current.interrupt();
      second = result.current.interrupt();
    });

    expect(second).toBe(first);
    await waitFor(() => expect(mockGetTaskTurns).toHaveBeenCalledTimes(1));

    resolveTurns?.(activeTurn('task-a', 'turn-a'));
    await waitFor(() => expect(mockInterruptTurn).toHaveBeenCalledTimes(1));
    expect(mockInterruptTurn).toHaveBeenCalledWith(
      'task-a',
      'turn-a',
      expect.stringMatching(/^turn\.interrupt/),
    );
    await act(async () => { await first; });
  });

  it('keeps the initiating Task for success invalidation when selection changes in flight', async () => {
    let resolveInterrupt: ((value: Awaited<ReturnType<typeof interruptTurn>>) => void) | undefined;
    mockGetTaskTurns.mockResolvedValue(activeTurn('task-a', 'turn-a'));
    mockInterruptTurn.mockImplementation(() => new Promise((resolve) => {
      resolveInterrupt = resolve;
    }));
    const client = createTestQueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result, rerender } = renderHook(
      ({ selectedTaskId }) => useTaskActions(selectedTaskId),
      { initialProps: { selectedTaskId: 'task-a' }, wrapper: wrapperFor(client) },
    );

    let request: Promise<void> | undefined;
    act(() => { request = result.current.interrupt(); });
    await waitFor(() => expect(mockInterruptTurn).toHaveBeenCalledTimes(1));
    rerender({ selectedTaskId: 'task-b' });
    expect(result.current.isInterruptPending).toBe(false);

    resolveInterrupt?.({
      control_request_id: 'control-1',
      expected_turn_id: 'turn-a',
      kind: 'interrupt',
      status: 'accepted',
      task_id: 'task-a',
    });
    await act(async () => { await request; });

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tasks.turns('task-a') }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tasks.detail('task-a') });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.tasks.messages('task-a') });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.tasks.detail('task-b') });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.tasks.messages('task-b') });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.tasks.turns('task-b') });
  });
});
