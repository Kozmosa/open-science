import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Dialog,
  FormField,
  Input,
  NativeSelect,
  RadioGroup,
  RadioGroupItem,
  Textarea,
} from '@design-system';
import { createTask, getSkills } from '@/shared/api';
import { useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import type { HarnessEngine, ResearcherType, SkillItem, TaskCreatePayload, TaskSummary } from '@/shared/types';
import {
  capabilityAvailability,
  getDomainCapabilities,
  getDomainProjects,
  getDomainWorkspaces,
  type DomainProjectProjection,
  type DomainWorkspaceProjection,
} from '@features/domain';
import { projectionReasonList } from '@features/domain/projectionReasons';
import { useLocale, useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import TaskSkillPicker from './TaskSkillPicker';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from '../utils/taskPresets';

export type TaskCreateSource = 'global' | 'project' | 'workspace' | 'literature';

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

  const payload = useMemo<TaskCreatePayload>(() => ({
    project_id: effectiveProjectId,
    workspace_id: effectiveWorkspaceId,
    researcher_type: researcherType,
    harness_engine: harnessEngine,
    prompt: prompt.trim(),
    skills: researcherType === 'vanilla' ? skills : [],
    mcp_servers: [],
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
      className="space-y-4 text-[var(--osci-color-text-primary)]"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) mutation.mutate();
      }}
    >
      {error ? <Alert variant="error">{error}</Alert> : null}
      {!capability.available && !capabilitiesQuery.isLoading ? (
        <Alert variant="warning">{capability.reason}</Alert>
      ) : null}
      <div className="grid gap-3 md:grid-cols-3">
        <FormField label={t('pages.tasks.projectLabel')}>
          <NativeSelect
            aria-label={t('pages.tasks.projectLabel')}
            value={effectiveProjectId}
            disabled={source === 'project' || lockedProjectId != null || projectsQuery.isLoading}
            onChange={(event) => {
              setProjectId(event.target.value);
              setWorkspaceId('');
            }}
          >
            <option value="">Select project</option>
            {projects.map((project: DomainProjectProjection) => (
              <option
                key={project.project_id}
                value={project.project_id}
                disabled={!project.permissions.can_create_task}
              >
                {project.name}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField label={t('pages.tasks.workspaceLabel')}>
          <NativeSelect
            aria-label={t('pages.tasks.workspaceLabel')}
            value={effectiveWorkspaceId}
            disabled={source === 'workspace' || lockedWorkspaceId != null || noExecutableWorkspace}
            onChange={(event) => setWorkspaceId(event.target.value)}
          >
            <option value="">Select workspace</option>
            {availableWorkspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField label={t('pages.tasks.environmentLabel')}>
          <Input
            aria-label={t('pages.tasks.environmentLabel')}
            readOnly
            value={selectedWorkspace
              ? `${selectedWorkspace.environment.display_name} (${selectedWorkspace.environment.alias})`
              : ''}
            placeholder="Derived from Workspace"
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
              Register or link Workspace
            </Button>
          </div>
        </Alert>
      ) : null}

      <FormField label={t('pages.tasks.create.taskPreset')}>
        <NativeSelect
          aria-label={t('pages.tasks.create.taskPreset')}
          value={presetId}
          onChange={(event) => applyPreset(event.target.value as TaskPresetId)}
        >
          {TASK_PRESET_OPTIONS.map((preset) => (
            <option key={preset.id} value={preset.id}>{t(preset.labelKey)}</option>
          ))}
        </NativeSelect>
      </FormField>

      {source !== 'literature' ? <FormField label={t('pages.tasks.create.researcherType')}>
        <RadioGroup
          aria-label={t('pages.tasks.create.researcherType')}
          value={researcherType}
          onValueChange={(value) => setResearcherType(value as ResearcherType)}
          className="flex flex-wrap gap-4"
        >
          <label className="flex items-center gap-2 text-sm">
            <RadioGroupItem value="vanilla" aria-label="Vanilla" />
            {t('pages.tasks.create.researcherVanilla')}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <RadioGroupItem value="aris-researcher" aria-label="ARIS Researcher" />
            {t('pages.tasks.create.researcherAris')}
          </label>
        </RadioGroup>
      </FormField> : null}

      {source !== 'literature' ? <FormField label={t('pages.tasks.create.executionEngine')}>
        <NativeSelect
          aria-label={t('pages.tasks.create.executionEngine')}
          value={harnessEngine}
          onChange={(event) => setHarnessEngine(event.target.value as HarnessEngine)}
        >
          <option value="claude-code">Claude Code</option>
          <option value="agent-sdk">Agent SDK</option>
          <option value="codex-app-server">Codex App Server</option>
        </NativeSelect>
      </FormField> : null}

      <FormField label={t('pages.tasks.titleLabel')}>
        <Input
          aria-label={t('pages.tasks.titleLabel')}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t('pages.tasks.create.titlePlaceholder')}
        />
      </FormField>
      {source !== 'literature' ? <FormField label={t('pages.tasks.taskInputLabel')}>
        <Textarea
          aria-label="Prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={t('pages.tasks.create.promptPlaceholder')}
          className="min-h-32"
        />
      </FormField> : null}
      {source !== 'literature' && researcherType === 'vanilla' ? (
        <TaskSkillPicker
          skills={(skillsQuery.data?.items ?? []) as SkillItem[]}
          selectedSkillIds={skills}
          onChange={setSkills}
        />
      ) : null}

      <div className="flex justify-end gap-2">
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
