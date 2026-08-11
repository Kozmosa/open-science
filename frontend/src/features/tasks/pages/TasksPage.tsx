import { Plus } from 'lucide-react';
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useSearchParams } from 'react-router-dom';
import {
  archiveTask,
  completeTask,
  confirmFork,
  getTask,
  getTaskTurns,
  getTasks,
  moveTask,
  previewFork,
  retryTask,
  reopenTask,
  unarchiveTask,
  updateTask,
} from '../api';
import { Button, Checkbox, Dialog, FormField, NativeSelect, PageShell, Sheet, SplitPane, Textarea, useToast } from '@design-system';
import { useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import {
  engineFamilyForHarnessEngine,
  FORK_HARNESS_ENGINES_BY_FAMILY,
  isTaskListSort,
} from '../types';
import type {
  ForkEngineFamily,
  ForkHarnessEngine,
  ForkPreview,
  ForkTransferMode,
  TaskListResponse,
  TaskListSort,
  TaskSummary,
} from '../types';
import { useAuth } from '@features/auth';
import {
  getDomainProjectContext,
  getDomainProjects,
  getDomainWorkspaces,
} from '@features/domain';
import TaskActionsMenu from '../components/TaskActionsMenu';
import TaskCreateFlow from '../components/TaskCreateFlow';
import TaskInspectorPanel, { type TaskDrawerView } from '../components/TaskInspectorPanel';
import TaskDetailPage from './TaskDetailPage';
import TaskList from './TaskList';
import { useTaskActions } from '../hooks/useTaskActions';
import { queryKeys } from '@/shared/api/queryKeys';
import { IdempotencyKeyManager, semanticMutationValue } from '@/shared/api/idempotency';

const SIDEBAR_COLLAPSED_WIDTH = 0;
const DEFAULT_TASK_SIDEBAR_WIDTH = 320;
const DEFAULT_METADATA_SIDEBAR_WIDTH = 320;
const DRAWER_VIEWS = new Set<TaskDrawerView>(['details', 'turns', 'context', 'closed']);
const NARROW_TASKS_QUERY = '(max-width: 1023px)';

type ForkPreviewMutationVariables = {
  sourceTaskId: string;
  sourceEngineFamily: ForkEngineFamily;
  targetProjectId: string;
  targetWorkspaceId: string;
  targetEngineFamily: ForkEngineFamily;
  targetHarnessEngine: ForkHarnessEngine;
  targetTitle?: string;
  transferMode: ForkTransferMode;
  flowGeneration: number;
  requestGeneration: number;
  locationKey: string;
};

type ForkPreviewMutationResult = {
  preview: ForkPreview;
  key: string;
  sourceTaskId: string;
  flowGeneration: number;
  requestGeneration: number;
  locationKey: string;
};

type ForkConfirmMutationVariables = {
  sourceTaskId: string;
  previewId: string;
  previewHash: string;
  sourceRevision: string;
  transferMode: ForkTransferMode;
  truncationAcknowledged: boolean;
  fullTranscriptConfirmed: boolean;
  flowGeneration: number;
  requestGeneration: number;
  locationKey: string;
};

type ForkConfirmMutationResult = ForkConfirmMutationVariables & {
  task: TaskSummary;
  key: string;
};

function usePageVisibility(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden');
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  return visible;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => (
    typeof window.matchMedia === 'function' && window.matchMedia(query).matches
  ));

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mediaQuery = window.matchMedia(query);
    const update = (event: MediaQueryListEvent) => setMatches(event.matches);
    mediaQuery.addEventListener('change', update);
    return () => mediaQuery.removeEventListener('change', update);
  }, [query]);

  return matches;
}

function TasksPage() {
  const t = useT();
  const { showToast } = useToast();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showArchived, setShowArchived] = useState(false);
  const [showFailedOrCancelled, setShowFailedOrCancelled] = useState(false);
  const [taskSort, setTaskSort] = useState<TaskListSort>('updated');
  const pageVisible = usePageVisibility();
  const isNarrow = useMediaQuery(NARROW_TASKS_QUERY);
  const requestedTaskId = searchParams.get('task');
  const hasRequestedTask = requestedTaskId !== null;
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks.list(showArchived, taskSort),
    queryFn: () => getTasks({ includeArchived: showArchived, limit: 200, sort: taskSort }),
    refetchInterval: pageVisible && !hasRequestedTask ? 15_000 : false,
  });

  const fetchedTasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const tasks = useMemo(
    () => showFailedOrCancelled
      ? fetchedTasks
      : fetchedTasks.filter((task) => task.status !== 'failed' && task.status !== 'cancelled'),
    [fetchedTasks, showFailedOrCancelled],
  );

  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [taskSearchQuery, setTaskSearchQuery] = useState('');
  const [taskSidebarWidth, setTaskSidebarWidth] = useState(DEFAULT_TASK_SIDEBAR_WIDTH);
  const [taskSidebarCollapsed, setTaskSidebarCollapsed] = useState(false);
  const [metadataSidebarWidth, setMetadataSidebarWidth] = useState(DEFAULT_METADATA_SIDEBAR_WIDTH);
  const [operationDialog, setOperationDialog] = useState<'move' | 'fork' | null>(null);
  const [targetProjectId, setTargetProjectId] = useState('');
  const [targetWorkspaceId, setTargetWorkspaceId] = useState('');
  const [forkTitle, setForkTitle] = useState('');
  const [forkTargetEngineFamily, setForkTargetEngineFamily] = useState<ForkEngineFamily | ''>('');
  const [forkTargetHarnessEngine, setForkTargetHarnessEngine] = useState<ForkHarnessEngine | ''>('');
  const [forkTransferMode, setForkTransferMode] = useState<ForkTransferMode>('full_transcript');
  const [forkPreview, setForkPreview] = useState<ForkPreview | null>(null);
  const [forkTruncationAcknowledged, setForkTruncationAcknowledged] = useState(false);
  const [forkFullTranscriptConfirmed, setForkFullTranscriptConfirmed] = useState(false);
  const [forkPreviewError, setForkPreviewError] = useState<unknown>(null);
  const [forkConfirmError, setForkConfirmError] = useState<unknown>(null);
  const createButtonRef = useRef<HTMLButtonElement>(null);
  const archiveKeyManager = useRef(new IdempotencyKeyManager('task.archive')).current;
  const unarchiveKeyManager = useRef(new IdempotencyKeyManager('task.unarchive')).current;
  const completeKeyManager = useRef(new IdempotencyKeyManager('task.complete')).current;
  const reopenKeyManager = useRef(new IdempotencyKeyManager('task.reopen')).current;
  const completeFlight = useRef(false);
  const reopenFlight = useRef(false);
  const retryKeyManager = useRef(new IdempotencyKeyManager('task.retry')).current;
  const moveKeyManager = useRef(new IdempotencyKeyManager('task.move')).current;
  const forkPreviewKeyManager = useRef(new IdempotencyKeyManager('task.fork.preview')).current;
  const forkConfirmKeyManager = useRef(new IdempotencyKeyManager('task.fork.confirm')).current;
  const renameKeyManager = useRef(new IdempotencyKeyManager('task.rename')).current;
  const forkFlowGeneration = useRef(0);
  const forkPreviewRequestGeneration = useRef(0);
  const forkConfirmRequestGeneration = useRef(0);
  const locationKeyRef = useRef(location.key);
  const selectedTaskIdRef = useRef<string | null>(null);
  const operationDialogRef = useRef<'move' | 'fork' | null>(null);
  const forkPreviewRef = useRef<ForkPreview | null>(null);
  const lastObservedSelectedTaskIdRef = useRef<string | null>(null);

  const advanceForkFlow = useCallback(() => {
    forkFlowGeneration.current += 1;
    return forkFlowGeneration.current;
  }, []);

  const effectiveSelectedTaskId = useMemo(() => {
    if (requestedTaskId && tasks.some((task) => task.task_id === requestedTaskId)) {
      return requestedTaskId;
    }
    if (isNarrow) {
      return null;
    }
    return tasks[0]?.task_id ?? null;
  }, [isNarrow, requestedTaskId, tasks]);

  const rawDrawer = searchParams.get('drawer');
  const drawerView: TaskDrawerView = rawDrawer && DRAWER_VIEWS.has(rawDrawer as TaskDrawerView)
    ? rawDrawer as TaskDrawerView
    : isNarrow ? 'closed' : 'details';

  const setDrawerView = useCallback((view: TaskDrawerView) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set('drawer', view);
      return next;
    });
  }, [setSearchParams]);

  const selectTask = useCallback(
    (taskId: string | null) => {
      if (selectedTaskIdRef.current !== taskId) {
        advanceForkFlow();
        selectedTaskIdRef.current = taskId;
        lastObservedSelectedTaskIdRef.current = taskId;
      }
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        if (taskId) {
          next.set('task', taskId);
        } else {
          next.delete('task');
        }
        return next;
      });
    },
    [advanceForkFlow, setSearchParams]
  );

  const selectTaskFromList = useCallback((taskId: string | null) => {
    if (selectedTaskIdRef.current !== taskId
      && (operationDialogRef.current === 'fork' || forkPreviewRef.current !== null)) {
      operationDialogRef.current = null;
      forkPreviewRef.current = null;
      setOperationDialog(null);
      setForkPreview(null);
      setForkTruncationAcknowledged(false);
      setForkFullTranscriptConfirmed(false);
      setForkPreviewError(null);
      setForkConfirmError(null);
    }
    selectTask(taskId);
  }, [selectTask]);

  const returnToTaskList = useCallback(() => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete('task');
      next.set('drawer', 'closed');
      return next;
    });
  }, [setSearchParams]);

  useEffect(() => {
    locationKeyRef.current = location.key;
  }, [location.key]);

  useEffect(() => {
    selectedTaskIdRef.current = effectiveSelectedTaskId;
    operationDialogRef.current = operationDialog;
    forkPreviewRef.current = forkPreview;
  }, [effectiveSelectedTaskId, forkPreview, operationDialog]);

  useEffect(() => {
    if (lastObservedSelectedTaskIdRef.current === effectiveSelectedTaskId) return;
    lastObservedSelectedTaskIdRef.current = effectiveSelectedTaskId;
    advanceForkFlow();
    if (operationDialogRef.current === 'fork' || forkPreviewRef.current !== null) {
      operationDialogRef.current = null;
      forkPreviewRef.current = null;
      startTransition(() => {
        setOperationDialog(null);
        setForkPreview(null);
        setForkTruncationAcknowledged(false);
        setForkFullTranscriptConfirmed(false);
        setForkPreviewError(null);
        setForkConfirmError(null);
      });
    }
  }, [advanceForkFlow, effectiveSelectedTaskId]);

  const toggleMetadataSidebar = useCallback(() => {
    setDrawerView(drawerView === 'closed' ? 'details' : 'closed');
  }, [drawerView, setDrawerView]);

  const toggleTaskSidebar = useCallback(() => {
    setTaskSidebarCollapsed((current) => !current);
  }, []);

  useEffect(() => {
    if (!isNarrow && effectiveSelectedTaskId && requestedTaskId !== effectiveSelectedTaskId) {
      selectTask(effectiveSelectedTaskId);
    }
  }, [effectiveSelectedTaskId, isNarrow, requestedTaskId, selectTask]);

  useEffect(() => {
    if (rawDrawer !== drawerView) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set('drawer', drawerView);
        return next;
      }, { replace: true });
    }
  }, [drawerView, rawDrawer, setSearchParams]);

  const selectedTaskQuery = useQuery({
    queryKey: queryKeys.tasks.detail(effectiveSelectedTaskId),
    queryFn: () => getTask(effectiveSelectedTaskId ?? ''),
    enabled: effectiveSelectedTaskId !== null,
    refetchInterval: pageVisible && !hasRequestedTask ? 15_000 : false,
  });

  const selectedTask = selectedTaskQuery.data ?? null;
  const taskActions = useTaskActions(effectiveSelectedTaskId);

  useEffect(() => {
    if (!effectiveSelectedTaskId || !pageVisible) {
      return undefined;
    }

    const refreshSelectedTask = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(effectiveSelectedTaskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(effectiveSelectedTaskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    };

    refreshSelectedTask();
    const interval = window.setInterval(refreshSelectedTask, 1_000);
    return () => window.clearInterval(interval);
  }, [effectiveSelectedTaskId, pageVisible, queryClient]);

  const domainProjectsQuery = useQuery({
    queryKey: queryKeys.domain.projects(true),
    queryFn: () => getDomainProjects(true),
  });
  const domainWorkspacesQuery = useQuery({
    queryKey: queryKeys.domain.workspaces(false),
    queryFn: () => getDomainWorkspaces(false),
  });

  const archiveMutation = useMutation({
    mutationFn: async (taskId: string) => {
      const key = archiveKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await archiveTask(taskId, key), key };
    },
    onSuccess: ({ key }) => {
      archiveKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.archived(true) });
    },
  });

  const unarchiveMutation = useMutation({
    mutationFn: async (taskId: string) => {
      const key = unarchiveKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await unarchiveTask(taskId, key), key };
    },
    onSuccess: ({ key }) => {
      unarchiveKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    },
  });

  const completeMutation = useMutation({
    mutationFn: async (taskId: string) => {
      const key = completeKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await completeTask(taskId, key), key, taskId };
    },
    onSuccess: ({ key, taskId }) => {
      completeKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      showToast(t('pages.tasks.completeSuccess'), 'success');
    },
    onError: () => {
      showToast(t('pages.tasks.completeFailed'), 'error');
    },
    onSettled: () => {
      completeFlight.current = false;
    },
  });

  const reopenMutation = useMutation({
    mutationFn: async (taskId: string) => {
      const key = reopenKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await reopenTask(taskId, key), key, taskId };
    },
    onSuccess: ({ key, taskId }) => {
      reopenKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      showToast(t('pages.tasks.reopenSuccess'), 'success');
    },
    onError: () => {
      showToast(t('pages.tasks.reopenFailed'), 'error');
    },
    onSettled: () => {
      reopenFlight.current = false;
    },
  });

  const triggerComplete = useCallback((taskId: string) => {
    if (completeFlight.current) return;
    completeFlight.current = true;
    completeMutation.mutate(taskId);
  }, [completeMutation]);

  const triggerReopen = useCallback((taskId: string) => {
    if (reopenFlight.current) return;
    reopenFlight.current = true;
    reopenMutation.mutate(taskId);
  }, [reopenMutation]);

  const retryMutation = useMutation({
    mutationFn: async (taskId: string) => {
      const key = retryKeyManager.keyFor(semanticMutationValue({ taskId }));
      return { result: await retryTask(taskId, key), key, taskId };
    },
    onSuccess: ({ key, taskId }) => {
      retryKeyManager.markSucceeded(key);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(taskId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.messages(taskId) });
      selectTask(taskId);
      showToast(t('pages.tasks.retrySuccess'), 'success');
    },
    onError: () => {
      showToast(t('pages.tasks.retryFailed'), 'error');
    },
  });

  const renameMutation = useMutation({
    mutationFn: async ({ taskId, title }: { taskId: string; title: string }) => {
      const key = renameKeyManager.keyFor(semanticMutationValue({ taskId, title }));
      return { task: await updateTask(taskId, { title }, key), key };
    },
    onSuccess: ({ task, key }) => {
      renameKeyManager.markSucceeded(key);
      queryClient.setQueriesData<TaskListResponse>(
        { queryKey: queryKeys.tasks.all },
        (current) => current ? {
          ...current,
          items: current.items.map((item) => item.task_id === task.task_id ? { ...item, ...task } : item),
        } : current,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.task_id) });
    },
    onError: () => {
      showToast(t('pages.tasks.renameFailed'), 'error');
    },
  });

  const targetContextQuery = useQuery({
    queryKey: queryKeys.domain.projectContext(targetProjectId || null),
    queryFn: () => getDomainProjectContext(targetProjectId),
    enabled: operationDialog === 'move' && targetProjectId !== '',
  });

  const moveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTask || !targetProjectId) throw new Error('Target Project is required');
      const contextVersionId = targetContextQuery.data?.active_version?.context_version_id;
      if (!contextVersionId) throw new Error('Target Project has no active Context Version');
      const input = {
        taskId: selectedTask.task_id,
        projectId: targetProjectId,
        contextVersionId,
      };
      const key = moveKeyManager.keyFor(semanticMutationValue(input));
      return { result: await moveTask(
        selectedTask.task_id,
        { project_id: targetProjectId, context_version_id: contextVersionId },
        key,
      ), key };
    },
    onSuccess: ({ key }) => {
      moveKeyManager.markSucceeded(key);
      setOperationDialog(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
    },
  });

  const isCurrentForkPreviewRequest = (
    request: Pick<ForkPreviewMutationVariables, 'sourceTaskId' | 'flowGeneration' | 'requestGeneration' | 'locationKey'>,
  ): boolean => request.flowGeneration === forkFlowGeneration.current
    && request.requestGeneration === forkPreviewRequestGeneration.current
    && request.sourceTaskId === selectedTaskIdRef.current
    && request.locationKey === locationKeyRef.current
    && operationDialogRef.current === 'fork';

  const isCurrentForkConfirmRequest = (
    request: Pick<ForkConfirmMutationVariables, 'sourceTaskId' | 'previewId' | 'flowGeneration' | 'requestGeneration' | 'locationKey'>,
  ): boolean => request.flowGeneration === forkFlowGeneration.current
    && request.requestGeneration === forkConfirmRequestGeneration.current
    && request.sourceTaskId === selectedTaskIdRef.current
    && request.locationKey === locationKeyRef.current
    && operationDialogRef.current === 'fork'
    && forkPreviewRef.current?.preview_id === request.previewId;

  const forkPreviewMutation = useMutation<ForkPreviewMutationResult, Error, ForkPreviewMutationVariables>({
    mutationFn: async (input) => {
      if (!input.targetWorkspaceId) throw new Error('Target Workspace is required');
      if (!input.targetProjectId) throw new Error('Target Project is required');
      if (input.targetEngineFamily === input.sourceEngineFamily) {
        throw new Error('Fork target engine must differ from the source engine');
      }
      const legalDrivers = FORK_HARNESS_ENGINES_BY_FAMILY[input.targetEngineFamily];
      if (!input.targetHarnessEngine || !legalDrivers.includes(input.targetHarnessEngine)) {
        throw new Error('Fork target driver does not match the target engine family');
      }
      const workspace = domainWorkspacesQuery.data?.items.find(
        (item) => item.workspace_id === input.targetWorkspaceId,
      );
      if (!workspace) throw new Error('Target Workspace is unavailable');
      if (!workspace.project_links.some(
        (link) => link.project_id === input.targetProjectId
          && link.link_status === 'active'
          && link.project_status === 'active'
          && link.can_execute,
      )) {
        throw new Error('Target Workspace is not executable for the selected Project');
      }
      const turns = input.transferMode === 'context_only'
        || input.transferMode === 'full_transcript'
        ? null
        : await getTaskTurns(input.sourceTaskId);
      const transferRange = input.transferMode === 'context_only'
        || input.transferMode === 'full_transcript'
        ? {}
        : input.transferMode === 'selected_turns'
          ? { turn_ids: turns?.items.map((turn) => turn.turn_id) ?? [] }
          : { count: Math.min(5, turns?.items.length ?? 0) };
      const payload = {
        target_engine_family: input.targetEngineFamily,
        target_project_id: input.targetProjectId,
        target_workspace_id: input.targetWorkspaceId,
        target_harness_engine: input.targetHarnessEngine,
        target_title: input.targetTitle,
        transfer_mode: input.transferMode,
        transfer_range: transferRange,
        metrics: {},
        disclosure: { caller: 'tasks-page' },
      };
      const key = forkPreviewKeyManager.keyFor(semanticMutationValue({
        taskId: input.sourceTaskId,
        targetProjectId: input.targetProjectId,
        targetWorkspaceId: input.targetWorkspaceId,
        targetEngineFamily: input.targetEngineFamily,
        targetHarnessEngine: input.targetHarnessEngine,
        targetTitle: input.targetTitle,
        transferMode: input.transferMode,
        transferRange,
      }));
      const preview = await previewFork(input.sourceTaskId, payload, key);
      return {
        preview,
        key,
        sourceTaskId: input.sourceTaskId,
        flowGeneration: input.flowGeneration,
        requestGeneration: input.requestGeneration,
        locationKey: input.locationKey,
      };
    },
    onSuccess: (result) => {
      forkPreviewKeyManager.markSucceeded(result.key);
      if (!isCurrentForkPreviewRequest(result)) return;
      setForkPreviewError(null);
      forkPreviewRef.current = result.preview;
      setForkPreview(result.preview);
      setForkTruncationAcknowledged(false);
      setForkFullTranscriptConfirmed(false);
    },
    onError: (error, input) => {
      if (isCurrentForkPreviewRequest(input)) setForkPreviewError(error);
    },
  });

  const forkConfirmMutation = useMutation<ForkConfirmMutationResult, Error, ForkConfirmMutationVariables>({
    mutationFn: async (input) => {
      const payload = {
        preview_hash: input.previewHash,
        source_revision: input.sourceRevision,
        transfer_mode: input.transferMode,
        truncation_acknowledged: input.truncationAcknowledged,
        full_transcript_confirmed: input.fullTranscriptConfirmed,
      };
      const key = forkConfirmKeyManager.keyFor(semanticMutationValue({
        taskId: input.sourceTaskId,
        previewId: input.previewId,
        previewHash: input.previewHash,
        sourceRevision: input.sourceRevision,
        transferMode: input.transferMode,
        truncationAcknowledged: input.truncationAcknowledged,
        fullTranscriptConfirmed: input.fullTranscriptConfirmed,
      }));
      const task = await confirmFork(input.sourceTaskId, input.previewId, payload, key);
      return { ...input, task, key };
    },
    onSuccess: async (result) => {
      forkConfirmKeyManager.markSucceeded(result.key);
      const refreshTasks = queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      if (!isCurrentForkConfirmRequest(result)) {
        await refreshTasks;
        return;
      }
      await refreshTasks;
      if (!isCurrentForkConfirmRequest(result)) return;
      operationDialogRef.current = null;
      forkPreviewRef.current = null;
      setOperationDialog(null);
      setForkPreview(null);
      setForkTruncationAcknowledged(false);
      setForkFullTranscriptConfirmed(false);
      setForkPreviewError(null);
      setForkConfirmError(null);
      selectTask(result.task.task_id);
    },
    onError: (error, input) => {
      if (isCurrentForkConfirmRequest(input)) setForkConfirmError(error);
    },
  });

  const sourceEngineFamily = selectedTask
    ? engineFamilyForHarnessEngine(selectedTask.harness_engine)
    : null;
  const forkTargetEngineOptions: ForkEngineFamily[] = sourceEngineFamily
    ? (['codex', 'claude'] as const).filter((family) => family !== sourceEngineFamily)
    : [];
  const forkTargetDrivers = forkTargetEngineFamily
    ? FORK_HARNESS_ENGINES_BY_FAMILY[forkTargetEngineFamily]
    : [];
  const forkRequiresFullTranscriptConfirmation = forkPreview?.transfer_mode === 'full_transcript';
  const forkConfirmDisabled = !forkPreview
    || (forkRequiresFullTranscriptConfirmation && !forkFullTranscriptConfirmed)
    || (forkPreview.truncated && !forkTruncationAcknowledged);

  const startForkPreview = useCallback(() => {
    if (!selectedTask || forkPreviewMutation.isPending) return;
    const sourceEngineFamily = engineFamilyForHarnessEngine(selectedTask.harness_engine);
    if (!sourceEngineFamily || !forkTargetEngineFamily || !forkTargetHarnessEngine || !targetProjectId || !targetWorkspaceId) {
      return;
    }
    const flowGeneration = advanceForkFlow();
    const requestGeneration = forkPreviewRequestGeneration.current + 1;
    forkPreviewRequestGeneration.current = requestGeneration;
    setForkPreviewError(null);
    setForkConfirmError(null);
    forkPreviewMutation.reset();
    forkPreviewMutation.mutate({
      sourceTaskId: selectedTask.task_id,
      sourceEngineFamily,
      targetProjectId,
      targetWorkspaceId,
      targetEngineFamily: forkTargetEngineFamily,
      targetHarnessEngine: forkTargetHarnessEngine,
      targetTitle: forkTitle.trim() || undefined,
      transferMode: forkTransferMode,
      flowGeneration,
      requestGeneration,
      locationKey: location.key,
    });
  }, [
    advanceForkFlow,
    forkPreviewMutation,
    forkTargetEngineFamily,
    forkTargetHarnessEngine,
    forkTitle,
    forkTransferMode,
    location.key,
    selectedTask,
    targetProjectId,
    targetWorkspaceId,
  ]);

  const startForkConfirm = useCallback(() => {
    const preview = forkPreviewRef.current;
    if (!preview || forkConfirmMutation.isPending) return;
    const flowGeneration = advanceForkFlow();
    const requestGeneration = forkConfirmRequestGeneration.current + 1;
    forkConfirmRequestGeneration.current = requestGeneration;
    setForkConfirmError(null);
    forkConfirmMutation.reset();
    forkConfirmMutation.mutate({
      sourceTaskId: preview.source_task_id,
      previewId: preview.preview_id,
      previewHash: preview.preview_hash,
      sourceRevision: preview.source_revision,
      transferMode: preview.transfer_mode,
      truncationAcknowledged: forkTruncationAcknowledged,
      fullTranscriptConfirmed: forkFullTranscriptConfirmed,
      flowGeneration,
      requestGeneration,
      locationKey: location.key,
    });
  }, [
    advanceForkFlow,
    forkConfirmMutation,
    forkFullTranscriptConfirmed,
    forkTruncationAcknowledged,
    location.key,
  ]);

  const openForkDialog = useCallback(() => {
    if (!selectedTask) return;
    const source = engineFamilyForHarnessEngine(selectedTask.harness_engine);
    const target = source === 'codex' ? 'claude' : source === 'claude' ? 'codex' : '';
    setTargetProjectId(selectedTask.project_id);
    setTargetWorkspaceId(selectedTask.workspace_id);
    setForkTitle('');
    setForkTargetEngineFamily(target);
    setForkTargetHarnessEngine(target ? FORK_HARNESS_ENGINES_BY_FAMILY[target][0] ?? '' : '');
    setForkTransferMode('full_transcript');
    setForkPreview(null);
    setForkTruncationAcknowledged(false);
    setForkFullTranscriptConfirmed(false);
    setForkPreviewError(null);
    setForkConfirmError(null);
    advanceForkFlow();
    operationDialogRef.current = 'fork';
    forkPreviewRef.current = null;
    forkPreviewMutation.reset();
    forkConfirmMutation.reset();
    setOperationDialog('fork');
  }, [advanceForkFlow, forkConfirmMutation, forkPreviewMutation, selectedTask]);

  const closeOperationDialog = useCallback(() => {
    advanceForkFlow();
    operationDialogRef.current = null;
    forkPreviewRef.current = null;
    setOperationDialog(null);
    setForkPreview(null);
    setForkTruncationAcknowledged(false);
    setForkFullTranscriptConfirmed(false);
    setForkPreviewError(null);
    setForkConfirmError(null);
    forkPreviewMutation.reset();
    forkConfirmMutation.reset();
  }, [advanceForkFlow, forkConfirmMutation, forkPreviewMutation]);

  const backToForkOptions = useCallback(() => {
    advanceForkFlow();
    forkPreviewRef.current = null;
    setForkPreview(null);
    setForkTruncationAcknowledged(false);
    setForkFullTranscriptConfirmed(false);
    setForkPreviewError(null);
    setForkConfirmError(null);
    forkConfirmMutation.reset();
  }, [advanceForkFlow, forkConfirmMutation]);

  const tasksError = extractErrorMessage(tasksQuery.error);
  const detailError = extractErrorMessage(selectedTaskQuery.error);
  const selectedProject = domainProjectsQuery.data?.items.find(
    (project) => project.project_id === selectedTask?.project_id,
  ) ?? null;
  const eligibleTargetProjects = (domainProjectsQuery.data?.items ?? []).filter(
    (project) => project.status === 'active' && project.permissions.can_create_task,
  );
  const ownsSelectedTask = Boolean(
    selectedTask && user && (user.role === 'admin' || selectedTask.owner_user_id === user.id),
  );
  const canMutateSelectedTask = ownsSelectedTask && selectedProject?.status === 'active';
  const mutationDisabledReason = !ownsSelectedTask
    ? 'Only the Task owner or an administrator can change this Task.'
    : selectedProject === null
      ? 'Project permissions are unavailable; Task actions remain disabled.'
      : selectedProject.status === 'archived'
      ? 'This Project is archived; execution actions are disabled.'
      : null;

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  const handleTaskCreated = useCallback((task: TaskSummary) => {
    queryClient.setQueryData<TaskListResponse>(
      queryKeys.tasks.list(showArchived, taskSort),
      (current) => ({
        items: [task, ...(current?.items ?? []).filter((item) => item.task_id !== task.task_id)],
        total: (current?.total ?? 0) + 1,
        has_more: current?.has_more ?? false,
        next_cursor: current?.next_cursor ?? null,
      }),
    );
    selectTask(task.task_id);
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(task.task_id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(false) });
  }, [queryClient, selectTask, showArchived, taskSort]);

  const effectiveTaskSidebarWidth = taskSidebarCollapsed
    ? SIDEBAR_COLLAPSED_WIDTH
    : taskSidebarWidth;
  const effectiveMetadataSidebarWidth = drawerView !== 'closed'
    ? metadataSidebarWidth
    : SIDEBAR_COLLAPSED_WIDTH;
  const forkDialogMatchesSelection = (!forkPreview || forkPreview.source_task_id === effectiveSelectedTaskId)
    && (!forkPreviewMutation.variables
      || forkPreviewMutation.variables.sourceTaskId === effectiveSelectedTaskId);

  const taskSidebarContent = taskSidebarCollapsed ? null : (
    <div className="flex min-h-0 flex-1 flex-col p-3">
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-[var(--osci-color-border-subtle)] pb-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--osci-color-primary)]">
            {t('pages.tasks.sidebarEyebrow')}
          </p>
          <p className="mt-1 truncate text-lg font-semibold tracking-tight text-[var(--osci-color-text)]">
            {t('pages.tasks.sidebarTitle')}
          </p>
          <p className="mt-1 text-xs text-[var(--osci-color-text-secondary)]">
            {t('pages.tasks.sidebarCount', { count: tasks.length })}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button
            ref={createButtonRef}
            size="sm"
            onClick={() => setCreateDialogOpen(true)}
          >
            <Plus size={14} />
            {t('pages.tasks.newTask')}
          </Button>
          <NativeSelect
            value={taskSort}
            onChange={(event) => {
              if (isTaskListSort(event.target.value)) setTaskSort(event.target.value);
            }}
            className="w-full rounded-lg py-1 text-[11px]"
          >
            <option value="updated">{t('pages.tasks.sort.updated')}</option>
            <option value="created">{t('pages.tasks.sort.created')}</option>
            <option value="name">{t('pages.tasks.sort.name')}</option>
          </NativeSelect>
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
            <label htmlFor="tasks-show-failed-cancelled" className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--osci-color-text-muted)]">
              <Checkbox
                id="tasks-show-failed-cancelled"
                checked={showFailedOrCancelled}
                onCheckedChange={(checked) => setShowFailedOrCancelled(checked === true)}
              />
              {t('pages.tasks.actions.showFailedOrCancelled')}
            </label>
            <label htmlFor="tasks-show-archived" className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--osci-color-text-muted)]">
              <Checkbox
                id="tasks-show-archived"
                checked={showArchived}
                onCheckedChange={(checked) => setShowArchived(checked === true)}
              />
              {t('pages.tasks.actions.showArchived')}
            </label>
          </div>
        </div>
      </div>

      <TaskList
        tasks={tasks}
        selectedTaskId={effectiveSelectedTaskId}
        tasksError={tasksError}
        searchQuery={taskSearchQuery}
        onSearchQueryChange={setTaskSearchQuery}
        onSelectTask={selectTaskFromList}
        canRenameTask={(task) => Boolean(
          user
          && (user.role === 'admin' || task.owner_user_id === user.id)
          && domainProjectsQuery.data?.items.some(
            (project) => project.project_id === task.project_id && project.status === 'active',
          )
        )}
        onRenameTask={(taskId, title) => renameMutation.mutate({ taskId, title })}
        renamingTaskId={renameMutation.isPending ? renameMutation.variables?.taskId ?? null : null}
      />
    </div>
  );

  return (
    <>
      <PageShell variant="canvas" className="gap-4 p-3">
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-xl border border-[var(--osci-color-border)]">
        {isNarrow ? (
          effectiveSelectedTaskId ? (
            <TaskDetailPage
              key={effectiveSelectedTaskId}
              taskId={effectiveSelectedTaskId}
              selectedTask={selectedTask}
              detailError={detailError}
              metadataSidebarOpen={drawerView !== 'closed'}
              onBackToList={returnToTaskList}
              onToggleMetadataSidebar={toggleMetadataSidebar}
              canMutate={canMutateSelectedTask}
              mutationDisabledReason={mutationDisabledReason}
              onInterrupt={taskActions.interrupt}
              interruptPending={taskActions.isInterruptPending}
              onSendPrompt={taskActions.sendPrompt}
              actionsPending={taskActions.isPending}
              headerActions={selectedTask ? (
                <TaskActionsMenu
                  task={selectedTask}
                  canMutate={canMutateSelectedTask}
                  disabledReason={mutationDisabledReason}
                  interruptPending={taskActions.isInterruptPending}
                  completePending={completeMutation.isPending}
                  reopenPending={reopenMutation.isPending}
                  onArchive={() => archiveMutation.mutate(selectedTask.task_id)}
                  onUnarchive={() => unarchiveMutation.mutate(selectedTask.task_id)}
                  onComplete={() => triggerComplete(selectedTask.task_id)}
                  onReopen={() => triggerReopen(selectedTask.task_id)}
                  onInterrupt={() => taskActions.interrupt()}
                  onRetry={() => retryMutation.mutate(selectedTask.task_id)}
                  onMove={() => {
                    setTargetProjectId(selectedTask.project_id);
                    setOperationDialog('move');
                  }}
                  onFork={openForkDialog}
                />
              ) : null}
            />
          ) : (
            <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col" data-testid="task-mobile-list">
              {taskSidebarContent}
            </div>
          )
        ) : (
        <SplitPane
          sidebar={taskSidebarContent}
          sidebarWidth={effectiveTaskSidebarWidth}
          onSidebarWidthChange={setTaskSidebarWidth}
          rightSidebar={
            selectedTask && drawerView !== 'closed' ? (
              <TaskInspectorPanel
                task={selectedTask}
                view={drawerView}
                onViewChange={setDrawerView}
              />
            ) : null
          }
          rightSidebarWidth={effectiveMetadataSidebarWidth}
          onRightSidebarWidthChange={setMetadataSidebarWidth}
          sidebarTestId="task-sidebar"
          rightSidebarTestId="task-metadata-sidebar"
          uniformSurface
        >
          <TaskDetailPage
            key={effectiveSelectedTaskId ?? 'none'}
            taskId={effectiveSelectedTaskId}
            selectedTask={selectedTask}
            detailError={detailError}
            taskSidebarCollapsed={taskSidebarCollapsed}
            metadataSidebarOpen={drawerView !== 'closed'}
            onToggleTaskSidebar={toggleTaskSidebar}
            onToggleMetadataSidebar={toggleMetadataSidebar}
            canMutate={canMutateSelectedTask}
            mutationDisabledReason={mutationDisabledReason}
            onInterrupt={taskActions.interrupt}
            interruptPending={taskActions.isInterruptPending}
            onSendPrompt={taskActions.sendPrompt}
            actionsPending={taskActions.isPending}
            headerActions={selectedTask ? (
              <TaskActionsMenu
                task={selectedTask}
                canMutate={canMutateSelectedTask}
                disabledReason={mutationDisabledReason}
                interruptPending={taskActions.isInterruptPending}
                completePending={completeMutation.isPending}
                reopenPending={reopenMutation.isPending}
                onArchive={() => archiveMutation.mutate(selectedTask.task_id)}
                onUnarchive={() => unarchiveMutation.mutate(selectedTask.task_id)}
                onComplete={() => triggerComplete(selectedTask.task_id)}
                onReopen={() => triggerReopen(selectedTask.task_id)}
                onInterrupt={() => taskActions.interrupt()}
                onRetry={() => retryMutation.mutate(selectedTask.task_id)}
                onMove={() => {
                  setTargetProjectId(selectedTask.project_id);
                  setOperationDialog('move');
                }}
                onFork={openForkDialog}
              />
            ) : null}
          />
        </SplitPane>
        )}
        </div>
      </PageShell>

      <TaskCreateFlow
        isOpen={isCreateDialogOpen}
        source="global"
        onClose={closeCreateDialog}
        onCreated={handleTaskCreated}
      />

      {isNarrow && selectedTask ? (
        <Sheet
          open={drawerView !== 'closed'}
          onOpenChange={(open) => setDrawerView(open ? 'details' : 'closed')}
          title="Task inspector"
        >
          <div className="h-full p-3">
            <TaskInspectorPanel
              task={selectedTask}
              view={drawerView === 'closed' ? 'details' : drawerView}
              onViewChange={setDrawerView}
            />
          </div>
        </Sheet>
      ) : null}

      <Dialog
        isOpen={operationDialog !== null && forkDialogMatchesSelection}
        onClose={closeOperationDialog}
        title={operationDialog === 'move' ? 'Move Task' : 'Fork Task'}
        size="md"
      >
        <div className="space-y-4">
          {operationDialog === 'fork' && forkPreview ? (
            <>
              <p className="text-sm font-medium text-[var(--osci-color-text)]">
                Step 2 of 2: review this preview and explicitly confirm. No target Task was created by the preview.
              </p>
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-x-4 gap-y-2 rounded-lg border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] p-3 text-sm">
                <dt className="text-[var(--osci-color-text-muted)]">Source engine</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">{forkPreview.source_engine_family}</dd>
                <dt className="text-[var(--osci-color-text-muted)]">Target engine</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">
                  {forkPreview.target_engine_family} ({forkPreview.target_harness_engine})
                </dd>
                <dt className="text-[var(--osci-color-text-muted)]">Transfer mode</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">{forkPreview.transfer_mode}</dd>
                <dt className="text-[var(--osci-color-text-muted)]">Target title</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">{forkPreview.target_title}</dd>
                <dt className="text-[var(--osci-color-text-muted)]">Transcript truncated</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">{forkPreview.truncated ? 'Yes' : 'No'}</dd>
                <dt className="text-[var(--osci-color-text-muted)]">Preview expires</dt>
                <dd className="font-medium text-[var(--osci-color-text)]">{forkPreview.expires_at}</dd>
              </dl>
              {forkRequiresFullTranscriptConfirmation ? (
                <label className="flex cursor-pointer items-start gap-2 text-sm text-[var(--osci-color-text)]">
                  <Checkbox
                    aria-label="Confirm full transcript transfer"
                    checked={forkFullTranscriptConfirmed}
                    onCheckedChange={(checked) => setForkFullTranscriptConfirmed(checked === true)}
                  />
                  <span>I explicitly confirm transferring the full transcript to the different target engine.</span>
                </label>
              ) : null}
              {forkPreview.truncated ? (
                <label className="flex cursor-pointer items-start gap-2 text-sm text-[var(--osci-color-text)]">
                  <Checkbox
                    aria-label="Acknowledge truncated transcript"
                    checked={forkTruncationAcknowledged}
                    onCheckedChange={(checked) => setForkTruncationAcknowledged(checked === true)}
                  />
                  <span>I acknowledge that the preview is truncated and the target will receive only the disclosed transfer.</span>
                </label>
              ) : null}
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-[var(--osci-color-text)]">
                Step 1 of 2: generate a preview only. The first click does not create a target Task.
              </p>
              <FormField label="Project">
                <NativeSelect
                  aria-label="Target Project"
                  value={targetProjectId}
                  onChange={(event) => {
                    setTargetProjectId(event.target.value);
                    setTargetWorkspaceId('');
                  }}
                >
                  <option value="">Select Project</option>
                  {eligibleTargetProjects
                    .map((project) => (
                      <option key={project.project_id} value={project.project_id}>{project.name}</option>
                    ))}
                </NativeSelect>
              </FormField>
            </>
          )}
          {operationDialog === 'fork' && !forkPreview ? (
            <>
              <FormField label="Workspace">
                <NativeSelect
                  aria-label="Target Workspace"
                  value={targetWorkspaceId}
                  onChange={(event) => setTargetWorkspaceId(event.target.value)}
                >
                  <option value="">Select Workspace</option>
                  {(domainWorkspacesQuery.data?.items ?? [])
                    .filter((workspace) => workspace.can_execute && workspace.project_links.some(
                      (link) => link.project_id === targetProjectId
                        && link.project_status === 'active'
                        && link.link_status === 'active'
                        && link.can_execute,
                    ))
                    .map((workspace) => (
                      <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.label}</option>
                    ))}
                </NativeSelect>
              </FormField>
              <FormField label="Target engine family">
                <NativeSelect
                  aria-label="Target engine family"
                  value={forkTargetEngineFamily}
                  onChange={(event) => {
                    const family = event.target.value as ForkEngineFamily;
                    setForkTargetEngineFamily(family);
                    setForkTargetHarnessEngine(FORK_HARNESS_ENGINES_BY_FAMILY[family]?.[0] ?? '');
                  }}
                  disabled={forkTargetEngineOptions.length === 0}
                >
                  <option value="">Select target engine</option>
                  {forkTargetEngineOptions.map((family) => (
                    <option key={family} value={family}>{family}</option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField label="Target driver">
                <NativeSelect
                  aria-label="Target driver"
                  value={forkTargetHarnessEngine}
                  onChange={(event) => setForkTargetHarnessEngine(event.target.value as ForkHarnessEngine)}
                  disabled={forkTargetDrivers.length === 0}
                >
                  <option value="">Select target driver</option>
                  {forkTargetDrivers.map((driver) => (
                    <option key={driver} value={driver}>{driver}</option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField label="Transfer mode">
                <NativeSelect
                  aria-label="Transfer mode"
                  value={forkTransferMode}
                  onChange={(event) => setForkTransferMode(event.target.value as ForkTransferMode)}
                >
                  <option value="selected_turns">Selected turns</option>
                  <option value="recent_turns">Recent turns</option>
                  <option value="full_transcript">Full transcript</option>
                  <option value="context_only">Context only</option>
                </NativeSelect>
              </FormField>
              <FormField label="Target title">
                <Textarea
                  aria-label="Target title"
                  value={forkTitle}
                  onChange={(event) => setForkTitle(event.target.value)}
                  placeholder="Optional title (defaults to Fork of the source Task)"
                />
              </FormField>
              {!sourceEngineFamily ? (
                <p className="text-sm text-[var(--osci-color-danger)]">
                  The source Task engine is not mapped to a supported Fork engine.
                </p>
              ) : null}
            </>
          ) : operationDialog === 'move' ? (
            <p className="text-sm text-[var(--osci-color-text-muted)]">
              The Task ID, Workspace, and Turn history remain unchanged. The target Project active Context Version will be pinned.
            </p>
          ) : null}
          {moveMutation.error instanceof Error ? <p className="text-sm text-[var(--osci-color-danger)]">{moveMutation.error.message}</p> : null}
          {extractErrorMessage(forkPreviewError) ? <p className="text-sm text-[var(--osci-color-danger)]">{extractErrorMessage(forkPreviewError)}</p> : null}
          {extractErrorMessage(forkConfirmError) ? <p className="text-sm text-[var(--osci-color-danger)]">{extractErrorMessage(forkConfirmError)}</p> : null}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={closeOperationDialog}>Cancel</Button>
            {operationDialog === 'fork' && forkPreview ? (
              <>
                <Button
                  variant="secondary"
                  onClick={backToForkOptions}
                >
                  Back to options
                </Button>
                <Button
                  onClick={startForkConfirm}
                  disabled={forkConfirmDisabled}
                  isLoading={forkConfirmMutation.isPending}
                >
                  Confirm Fork
                </Button>
              </>
            ) : (
              <Button
                onClick={() => operationDialog === 'move' ? moveMutation.mutate() : startForkPreview()}
                disabled={operationDialog === 'move'
                  ? !targetContextQuery.data?.active_version?.context_version_id
                  : !targetProjectId || !targetWorkspaceId || !forkTargetEngineFamily || !forkTargetHarnessEngine
                    || forkTargetEngineFamily === sourceEngineFamily}
                isLoading={moveMutation.isPending || forkPreviewMutation.isPending}
              >
                {operationDialog === 'move' ? 'Move Task' : 'Preview Fork'}
              </Button>
            )}
          </div>
        </div>
      </Dialog>
    </>
  );
}

export default TasksPage;
