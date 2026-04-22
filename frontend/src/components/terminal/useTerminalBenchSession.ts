import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createTerminalSession,
  deleteTerminalSession,
  getTerminalSession,
  resetTerminalSession,
} from '../../api';
import type { EnvironmentRecord, TerminalSession, TerminalSessionStatus } from '../../types';

const terminalSessionQueryKey = ['terminal-session'] as const;

export interface TerminalBenchSessionState {
  sessionId: string | null;
  sessionName: string | null;
  attachmentId: string | null;
  status: TerminalSessionStatus;
  terminalWsUrl: string | null;
  detail: string | null;
  loadError: string | null;
  isLoading: boolean;
  isAttaching: boolean;
  isDetaching: boolean;
  isResetting: boolean;
  canAttach: boolean;
  canDetach: boolean;
  canReset: boolean;
  onAttach: () => void;
  onDetach: () => void;
  onReset: () => void;
  onTerminalDisconnected: () => void;
}

function getErrorMessage(error: unknown): string | null {
  return error instanceof Error ? error.message : null;
}

function idleTerminalSession(): TerminalSession {
  return {
    session_id: null,
    provider: 'tmux',
    target_kind: 'daemon-host',
    environment_id: null,
    environment_alias: null,
    working_directory: null,
    status: 'idle',
    created_at: null,
    started_at: null,
    closed_at: null,
    terminal_ws_url: null,
    detail: null,
    binding_id: null,
    session_name: null,
    attachment_id: null,
    attachment_expires_at: null,
  };
}

export function useTerminalBenchSession(
  selectedEnvironment: EnvironmentRecord | null
): TerminalBenchSessionState {
  const queryClient = useQueryClient();
  const selectedEnvironmentId = selectedEnvironment?.id ?? null;
  const previousEnvironmentIdRef = useRef<string | null>(selectedEnvironmentId);
  const autoAttachKeyRef = useRef<string | null>(null);
  const [detachedEnvironmentId, setDetachedEnvironmentId] = useState<string | null>(null);

  const terminalQuery = useQuery({
    queryKey: [...terminalSessionQueryKey, selectedEnvironmentId],
    queryFn: () => {
      if (selectedEnvironmentId === null) {
        return Promise.resolve<TerminalSession>(idleTerminalSession());
      }
      return getTerminalSession(selectedEnvironmentId);
    },
  });

  const attachMutation = useMutation({
    mutationFn: (environmentId: string) => createTerminalSession(environmentId),
    onSuccess: (session, environmentId) => {
      queryClient.setQueryData([...terminalSessionQueryKey, environmentId], session);
    },
  });

  const detachMutation = useMutation({
    mutationFn: (payload: { environmentId: string; attachmentId: string | null }) =>
      deleteTerminalSession(payload),
    onSuccess: (session, payload) => {
      queryClient.setQueryData([...terminalSessionQueryKey, payload.environmentId], session);
    },
  });

  const resetMutation = useMutation({
    mutationFn: (payload: { environmentId: string; attachmentId: string | null }) =>
      resetTerminalSession(payload.environmentId, payload.attachmentId),
    onSuccess: (session, payload) => {
      queryClient.setQueryData([...terminalSessionQueryKey, payload.environmentId], session);
    },
  });

  useEffect(() => {
    if (previousEnvironmentIdRef.current === selectedEnvironmentId) {
      return;
    }
    previousEnvironmentIdRef.current = selectedEnvironmentId;
    autoAttachKeyRef.current = null;
    queueMicrotask(() => {
      setDetachedEnvironmentId(null);
    });
  }, [selectedEnvironmentId]);

  const session = terminalQuery.data;
  const shouldAutoAttach =
    selectedEnvironmentId !== null &&
    !terminalQuery.isLoading &&
    !attachMutation.isPending &&
    !detachMutation.isPending &&
    !resetMutation.isPending &&
    detachedEnvironmentId !== selectedEnvironmentId &&
    session?.status === 'running' &&
    session.attachment_id === null;

  useEffect(() => {
    if (!shouldAutoAttach || selectedEnvironmentId === null || session === undefined) {
      autoAttachKeyRef.current = null;
      return;
    }
    const autoAttachKey = `${selectedEnvironmentId}:${session.session_name ?? 'none'}:${session.status}`;
    if (autoAttachKeyRef.current === autoAttachKey) {
      return;
    }
    autoAttachKeyRef.current = autoAttachKey;
    attachMutation.mutate(selectedEnvironmentId);
  }, [attachMutation, selectedEnvironmentId, session, shouldAutoAttach]);

  const status = session?.status ?? 'idle';
  const loadError = getErrorMessage(terminalQuery.error);
  const mutationError =
    getErrorMessage(attachMutation.error) ??
    getErrorMessage(detachMutation.error) ??
    getErrorMessage(resetMutation.error);
  const detail = mutationError ?? session?.detail ?? null;
  const isLoading = terminalQuery.isLoading;
  const isAttaching = attachMutation.isPending;
  const isDetaching = detachMutation.isPending;
  const isResetting = resetMutation.isPending;
  const isBusy = isAttaching || isDetaching || isResetting;
  const canAttach =
    selectedEnvironmentId !== null &&
    !isLoading &&
    loadError === null &&
    !isBusy &&
    session?.attachment_id === null;
  const canDetach =
    selectedEnvironmentId !== null &&
    !isLoading &&
    loadError === null &&
    !isBusy &&
    session?.attachment_id !== null;
  const canReset = selectedEnvironmentId !== null && !isLoading && loadError === null && !isBusy;

  return {
    sessionId: session?.session_id ?? null,
    sessionName: session?.session_name ?? null,
    attachmentId: session?.attachment_id ?? null,
    status,
    terminalWsUrl: session?.terminal_ws_url ?? null,
    detail,
    loadError,
    isLoading,
    isAttaching,
    isDetaching,
    isResetting,
    canAttach,
    canDetach,
    canReset,
    onAttach: () => {
      if (selectedEnvironmentId === null) {
        return;
      }
      autoAttachKeyRef.current = null;
      setDetachedEnvironmentId(null);
      attachMutation.mutate(selectedEnvironmentId);
    },
    onDetach: () => {
      const currentAttachmentId = session?.attachment_id ?? null;
      if (selectedEnvironmentId === null || currentAttachmentId === null) {
        return;
      }
      autoAttachKeyRef.current = null;
      setDetachedEnvironmentId(selectedEnvironmentId);
      detachMutation.mutate({
        environmentId: selectedEnvironmentId,
        attachmentId: currentAttachmentId,
      });
    },
    onReset: () => {
      if (selectedEnvironmentId === null) {
        return;
      }
      autoAttachKeyRef.current = null;
      setDetachedEnvironmentId(null);
      resetMutation.mutate({
        environmentId: selectedEnvironmentId,
        attachmentId: session?.attachment_id ?? null,
      });
    },
    onTerminalDisconnected: () => {
      queryClient.invalidateQueries({
        queryKey: [...terminalSessionQueryKey, selectedEnvironmentId],
      });
    },
  };
}
