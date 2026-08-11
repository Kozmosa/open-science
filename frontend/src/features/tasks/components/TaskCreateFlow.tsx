import { useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Dialog,
  FormField,
  Input,
  RadioGroup,
  RadioGroupItem,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from '@design-system';
import { getSkills } from '@features/settings';
import { createTask } from '../api';
import { useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import type { HarnessEngine, ResearcherType, TaskCreateInput, TaskSummary } from '../types';
import {
  capabilityAvailability,
  getDomainCapabilities,
  getDomainProjects,
  getDomainWorkspaces,
  type DomainProjectProjection,
  type DomainWorkspaceProjection,
} from '@features/domain';
import { projectionReasonList } from '@features/domain/projectionReasons';
import { useLocale, useT, type MessageKey } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import TaskSkillPicker from './TaskSkillPicker';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from '../utils/taskPresets';

export type TaskCreateSource = 'global' | 'project' | 'workspace' | 'literature';

const CAPABILITY_REASON_KEYS: Partial<Record<string, MessageKey>> = {
  'OpenScience capabilities are still loading.': 'pages.tasks.create.capabilityLoading',
  'Task execution is paused for maintenance.': 'pages.tasks.create.taskExecutionMaintenance',
  'The task dispatcher heartbeat is stale.': 'pages.tasks.create.taskDispatcherStale',
  'No active task dispatcher is available.': 'pages.tasks.create.taskDispatcherUnavailable',
  'The overview snapshot store is unavailable.': 'pages.tasks.create.overviewSnapshotUnavailable',
};

interface TaskCreateSelectProps {
  ariaLabel: string;
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
  placeholder?: string;
  disabled?: boolean;
}

function TaskCreateSelect({
  ariaLabel,
  value,
  onValueChange,
  children,
  placeholder,
  disabled = false,
}: TaskCreateSelectProps) {
  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger aria-label={ariaLabel} className="min-h-9 px-3 py-1.5">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

interface TaskCreateFlowProps {
  isOpen: boolean;
  source: TaskCreateSource;
  onClose: () => void;
  lockedProjectId?: string | null;
  lockedWorkspaceId?: string | null;
  initialTitle?: string;
  initialPrompt?: string;
  onCreated?: (task: TaskSummary) => void;
  onLiteratureSubmit?: (selection: {
    project_id: string;
    workspace_id: string;
    task_preset: TaskPresetId;
    title?: string;
  }) => Promise<void>;
}

function executableWorkspaces(
  workspaces: DomainWorkspaceProjection[],
  projectId: string,
): DomainWorkspaceProjection[] {
  return workspaces.filter((workspace) =>
    workspace.status === 'active'
    && workspace.can_execute
    && workspace.project_links.some((link) =>
      link.project_id === projectId
      && link.project_status === 'active'
      && link.link_status === 'active'
      && link.can_execute,
    ),
  );
}

function TaskCreateFlowContent({
  source,
  onClose,
  lockedProjectId,
  lockedWorkspaceId,
  initialTitle = '',
  initialPrompt = '',
  onCreated,
  onLiteratureSubmit,
}: Omit<TaskCreateFlowProps, 'isOpen'>) {
  const t = useT();
  const locale = useLocale();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projectsQuery = useQuery({
    queryKey: queryKeys.domain.projects(false),
    queryFn: () => getDomainProjects(false),
  });
  const workspacesQuery = useQuery({
    queryKey: queryKeys.domain.workspaces(false),
    queryFn: () => getDomainWorkspaces(false),
  });
  const capabilitiesQuery = useQuery({
    queryKey: queryKeys.domain.capabilities,
    queryFn: getDomainCapabilities,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.all,
    queryFn: getSkills,
  });

  const projects = useMemo(
    () => (projectsQuery.data?.items ?? []).filter((project) => project.status === 'active'),
    [projectsQuery.data],
  );
  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const lockedWorkspace = lockedWorkspaceId
    ? workspaces.find((workspace) => workspace.workspace_id === lockedWorkspaceId) ?? null
    : null;
  const initialProjectId = lockedProjectId
    ?? lockedWorkspace?.project_links.find((link) =>
      link.project_status === 'active'
      && link.link_status === 'active'
      && link.can_execute
      && projects.some((project) =>
        project.project_id === link.project_id && project.permissions.can_create_task,
      ),
    )?.project_id
    ?? projects.find((project) => project.permissions.can_create_task)?.project_id
    ?? projects[0]?.project_id
    ?? '';
  const [projectId, setProjectId] = useState(initialProjectId);
  const [workspaceId, setWorkspaceId] = useState(lockedWorkspaceId ?? '');
  const [presetId, setPresetId] = useState<TaskPresetId>('raw-prompt');
  const initialPreset = getTaskPreset('raw-prompt');
  const [researcherType, setResearcherType] = useState<ResearcherType>(initialPreset.researcherType);
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>(initialPreset.harnessEngine);
  const [title, setTitle] = useState(initialTitle);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [skills, setSkills] = useState<string[]>([]);
  const effectiveProjectId = projectId || initialProjectId;

  const availableWorkspaces = useMemo(
    () => executableWorkspaces(workspaces, effectiveProjectId),
    [effectiveProjectId, workspaces],
  );
  const effectiveWorkspaceId = lockedWorkspaceId
    ?? (availableWorkspaces.some((workspace) => workspace.workspace_id === workspaceId)
      ? workspaceId
        : availableWorkspaces.find((workspace) =>
          workspace.project_links.some(
            (link) => link.project_id === effectiveProjectId && link.is_primary,
          ),
        )?.workspace_id ?? availableWorkspaces[0]?.workspace_id ?? '');
  const selectedWorkspace = workspaces.find(
    (workspace) => workspace.workspace_id === effectiveWorkspaceId,
  ) ?? null;
  const selectedWorkspaceIsExecutable = availableWorkspaces.some(
    (workspace) => workspace.workspace_id === effectiveWorkspaceId,
  );
  const selectedProject = projects.find(
    (project) => project.project_id === effectiveProjectId,
  ) ?? null;
  const capability = capabilityAvailability(
    capabilitiesQuery.data ?? null,
    'standard_task_create',
  );

  const payload = useMemo<TaskCreateInput>(() => ({
    projectId: effectiveProjectId,
    workspaceId: effectiveWorkspaceId,
    researcherType,
    harnessEngine,
    prompt: prompt.trim(),
    skills: researcherType === 'vanilla' ? skills : [],
    mcpServers: [],
    title: title.trim() || undefined,
  }), [effectiveProjectId, effectiveWorkspaceId, harnessEngine, prompt, researcherType, skills, title]);
  const { idempotencyKey, markSucceeded } = useIdempotencyKey('task.create', payload);
  const mutation = useMutation({
    mutationFn: async (): Promise<TaskSummary | null> => {
      if (source === 'literature' && onLiteratureSubmit) {
        await onLiteratureSubmit({
          project_id: effectiveProjectId,
          workspace_id: effectiveWorkspaceId,
          task_preset: presetId,
          title: title.trim() || undefined,
        });
        return null;
      }
      return createTask(payload, idempotencyKey);
    },
    onSuccess: (task) => {
      markSucceeded();
      if (task && onCreated) {
        onCreated(task);
      } else if (task) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.projectTasks.byProject(effectiveProjectId),
        });
      }
      onClose();
    },
  });
  const error = extractErrorMessage(
    projectsQuery.error ?? workspacesQuery.error ?? capabilitiesQuery.error ?? mutation.error,
  );
  const noExecutableWorkspace = effectiveProjectId !== '' && availableWorkspaces.length === 0;
  const noExecutableReasons = projectionReasonList(locale, [
    lockedWorkspace?.cannot_execute_reason,
    ...(selectedProject?.attention_reasons ?? []),
    noExecutableWorkspace ? 'no_executable_workspace' : null,
  ]);
  const capabilityReason = capability.reason
    ? t(CAPABILITY_REASON_KEYS[capability.reason] ?? 'pages.tasks.create.capabilityUnavailable')
    : null;
  const canSubmit = capability.available
    && selectedProject?.permissions.can_create_task === true
    && selectedWorkspace !== null
    && selectedWorkspaceIsExecutable
    && (source === 'literature' || prompt.trim() !== '')
    && !mutation.isPending;

  const applyPreset = (nextPresetId: TaskPresetId) => {
    const preset = getTaskPreset(nextPresetId);
    setPresetId(preset.id);
    setResearcherType(preset.researcherType);
    setHarnessEngine(preset.harnessEngine);
  };

  return (
    <form
      className="space-y-3 text-[var(--osci-color-text)]"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) mutation.mutate();
      }}
    >
      {error ? <Alert variant="error">{error}</Alert> : null}
      {!capability.available && !capabilitiesQuery.isLoading ? (
        <Alert variant="warning">{capabilityReason}</Alert>
      ) : null}
      <div className="grid gap-2.5 min-[480px]:grid-cols-2 lg:grid-cols-3">
        <FormField className="space-y-1.5" label={t('pages.tasks.projectLabel')}>
          <TaskCreateSelect
            ariaLabel={t('pages.tasks.projectLabel')}
            value={effectiveProjectId}
            placeholder={t('pages.tasks.create.selectProject')}
            disabled={source === 'project' || lockedProjectId != null || projectsQuery.isLoading}
            onValueChange={(value) => {
              setProjectId(value);
              setWorkspaceId('');
            }}
          >
            {projects.map((project: DomainProjectProjection) => (
              <SelectItem
                key={project.project_id}
                value={project.project_id}
                disabled={!project.permissions.can_create_task}
              >
                {project.name}
              </SelectItem>
            ))}
          </TaskCreateSelect>
        </FormField>
        <FormField className="space-y-1.5" label={t('pages.tasks.workspaceLabel')}>
          <TaskCreateSelect
            ariaLabel={t('pages.tasks.workspaceLabel')}
            value={effectiveWorkspaceId}
            placeholder={t('pages.tasks.create.selectWorkspace')}
            disabled={source === 'workspace' || lockedWorkspaceId != null || noExecutableWorkspace}
            onValueChange={setWorkspaceId}
          >
            {availableWorkspaces.map((workspace) => (
              <SelectItem key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </SelectItem>
            ))}
          </TaskCreateSelect>
        </FormField>
        <FormField className="space-y-1.5" label={t('pages.tasks.environmentLabel')}>
          <Input
            aria-label={t('pages.tasks.environmentLabel')}
            readOnly
            className="py-2"
            value={selectedWorkspace
              ? `${selectedWorkspace.environment.display_name} (${selectedWorkspace.environment.alias})`
              : ''}
            placeholder={t('pages.tasks.create.derivedEnvironment')}
          />
        </FormField>
      </div>

      {noExecutableWorkspace ? (
        <Alert variant="warning">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span>{noExecutableReasons.join(' ')}</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                onClose();
                navigate('/workspaces');
              }}
            >
              {t('pages.tasks.create.registerWorkspace')}
            </Button>
          </div>
        </Alert>
      ) : null}

      <div className="grid gap-2.5 min-[480px]:grid-cols-2">
        <FormField className="space-y-1.5" label={t('pages.tasks.create.taskPreset')}>
          <TaskCreateSelect
            ariaLabel={t('pages.tasks.create.taskPreset')}
            value={presetId}
            onValueChange={(value) => applyPreset(value as TaskPresetId)}
          >
            {TASK_PRESET_OPTIONS.map((preset) => (
              <SelectItem key={preset.id} value={preset.id}>{t(preset.labelKey)}</SelectItem>
            ))}
          </TaskCreateSelect>
        </FormField>
        {source !== 'literature' ? <FormField className="space-y-1.5" label={t('pages.tasks.create.executionEngine')}>
          <TaskCreateSelect
            ariaLabel={t('pages.tasks.create.executionEngine')}
            value={harnessEngine}
            onValueChange={(value) => setHarnessEngine(value as HarnessEngine)}
          >
            <SelectItem value="claude-code">{t('pages.tasks.create.engineClaudeCode')}</SelectItem>
            <SelectItem value="agent-sdk">{t('pages.tasks.create.engineAgentSdk')}</SelectItem>
            <SelectItem value="codex-app-server">{t('pages.tasks.create.engineCodexAppServer')}</SelectItem>
          </TaskCreateSelect>
        </FormField> : null}
      </div>

      {source !== 'literature' ? <FormField className="space-y-1.5" label={t('pages.tasks.create.researcherType')}>
        <RadioGroup
          aria-label={t('pages.tasks.create.researcherType')}
          value={researcherType}
          onValueChange={(value) => setResearcherType(value as ResearcherType)}
          className="flex flex-wrap gap-2"
        >
          <label className="inline-flex min-h-9 items-center gap-2 rounded-[var(--osci-radius-sm)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-2.5 text-sm transition hover:border-[var(--osci-color-primary)]">
            <RadioGroupItem value="vanilla" aria-label={t('pages.tasks.create.researcherVanilla')} />
            {t('pages.tasks.create.researcherVanilla')}
          </label>
          <label className="inline-flex min-h-9 items-center gap-2 rounded-[var(--osci-radius-sm)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-2.5 text-sm transition hover:border-[var(--osci-color-primary)]">
            <RadioGroupItem value="aris-researcher" aria-label={t('pages.tasks.create.researcherAris')} />
            {t('pages.tasks.create.researcherAris')}
          </label>
        </RadioGroup>
      </FormField> : null}

      <FormField className="space-y-1.5" label={t('pages.tasks.titleLabel')}>
        <Input
          aria-label={t('pages.tasks.titleLabel')}
          className="py-2"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t('pages.tasks.create.titlePlaceholder')}
        />
      </FormField>
      {source !== 'literature' ? <FormField className="space-y-1.5" label={t('pages.tasks.taskInputLabel')}>
        <Textarea
          aria-label={t('pages.tasks.create.promptLabel')}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={t('pages.tasks.create.promptPlaceholder')}
          className="min-h-32"
        />
      </FormField> : null}
      {source !== 'literature' && researcherType === 'vanilla' ? (
        <TaskSkillPicker
          skills={skillsQuery.data?.items ?? []}
          selectedSkillIds={skills}
          onChange={setSkills}
        />
      ) : null}

      <div className="flex justify-end gap-2 pt-1">
        <Button type="button" variant="secondary" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" disabled={!canSubmit} isLoading={mutation.isPending}>
          {mutation.isPending ? t('pages.tasks.creatingAction') : t('pages.tasks.createAction')}
        </Button>
      </div>
    </form>
  );
}

export default function TaskCreateFlow(props: TaskCreateFlowProps) {
  const t = useT();
  return (
    <Dialog
      isOpen={props.isOpen}
      onClose={props.onClose}
      title={null}
      ariaLabel={t('pages.tasks.createTitle')}
      size="lg"
    >
      {props.isOpen ? (
        <TaskCreateFlowContent
          key={`${props.source}:${props.lockedProjectId ?? ''}:${props.lockedWorkspaceId ?? ''}`}
          source={props.source}
          onClose={props.onClose}
          lockedProjectId={props.lockedProjectId}
          lockedWorkspaceId={props.lockedWorkspaceId}
          initialTitle={props.initialTitle}
          initialPrompt={props.initialPrompt}
          onCreated={props.onCreated}
          onLiteratureSubmit={props.onLiteratureSubmit}
        />
      ) : null}
    </Dialog>
  );
}
