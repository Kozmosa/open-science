import { useEffect, useState } from 'react';
import { Button, FormField, Input, Select, Textarea } from '../../components/ui';
import { useT } from '../../i18n';
import type { EnvironmentRecord, ProjectRecord, SkillItem, TaskCreatePayload, ResearcherType, HarnessEngine, WorkspaceRecord } from '../../types';
import TaskSkillPicker from './TaskSkillPicker';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from './taskPresets';

const FIELD_IDS = {
  project: 'task-create-project',
  workspace: 'task-create-workspace',
  environment: 'task-create-environment',
  taskPreset: 'task-create-preset',
  researcherVanilla: 'task-create-researcher-vanilla',
  researcherAris: 'task-create-researcher-aris',
  harnessEngine: 'task-create-harness-engine',
  title: 'task-create-title',
  prompt: 'task-create-prompt',
};

interface Props {
  projectId: string;
  workspaceId: string;
  environmentId: string;
  availableProjects: ProjectRecord[];
  availableWorkspaces: WorkspaceRecord[];
  availableEnvironments: EnvironmentRecord[];
  availableSkills: SkillItem[];
  lockProject?: boolean;
  onSubmit: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function TaskCreateForm({
  projectId,
  workspaceId,
  environmentId,
  availableProjects,
  availableWorkspaces,
  availableEnvironments,
  availableSkills,
  lockProject = false,
  onSubmit,
  onCancel,
}: Props) {
  const t = useT();
  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(workspaceId);
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState(environmentId);
  const [selectedTaskPresetId, setSelectedTaskPresetId] = useState<TaskPresetId>('raw-prompt');
  const [researcherType, setResearcherType] = useState<ResearcherType>('vanilla');
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>('claude-code');
  const [prompt, setPrompt] = useState('');
  const [skills, setSkills] = useState<string[]>([]);
  const [title, setTitle] = useState('');

  useEffect(() => {
    setSelectedProjectId(projectId);
  }, [projectId]);

  useEffect(() => {
    setSelectedWorkspaceId(workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    setSelectedEnvironmentId(environmentId);
  }, [environmentId]);

  const handleProjectChange = (nextProjectId: string) => {
    setSelectedProjectId(nextProjectId);
    const project = availableProjects.find(item => item.project_id === nextProjectId);
    if (project?.default_workspace_id && availableWorkspaces.some(item => item.workspace_id === project.default_workspace_id)) {
      setSelectedWorkspaceId(project.default_workspace_id);
    }
    if (project?.default_environment_id && availableEnvironments.some(item => item.id === project.default_environment_id)) {
      setSelectedEnvironmentId(project.default_environment_id);
    }
  };

  const applyTaskPreset = (presetId: TaskPresetId) => {
    const preset = getTaskPreset(presetId);
    setSelectedTaskPresetId(preset.id);
    setResearcherType(preset.researcherType);
    setHarnessEngine(preset.harnessEngine);
  };


  const canSubmit = selectedProjectId !== '' && selectedWorkspaceId !== '' && selectedEnvironmentId !== '' && prompt.trim() !== '';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      return;
    }
    onSubmit({
      project_id: selectedProjectId,
      workspace_id: selectedWorkspaceId,
      environment_id: selectedEnvironmentId,
      researcher_type: researcherType,
      harness_engine: harnessEngine,
      prompt,
      skills: researcherType === 'vanilla' ? skills : [],
      mcp_servers: [],
      title: title || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 text-[var(--text)]">
      <div className="grid gap-3 md:grid-cols-3">
        <FormField label={t('pages.tasks.projectLabel')}>
          <Select
            id={FIELD_IDS.project}
            value={selectedProjectId}
            onChange={(e) => handleProjectChange(e.target.value)}
            disabled={lockProject || availableProjects.length === 0}
          >
            {availableProjects.map(project => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label={t('pages.tasks.workspaceLabel')}>
          <Select
            id={FIELD_IDS.workspace}
            value={selectedWorkspaceId}
            onChange={(e) => setSelectedWorkspaceId(e.target.value)}
            disabled={availableWorkspaces.length === 0}
          >
            {availableWorkspaces.map(workspace => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label={t('pages.tasks.environmentLabel')}>
          <Select
            id={FIELD_IDS.environment}
            value={selectedEnvironmentId}
            onChange={(e) => setSelectedEnvironmentId(e.target.value)}
            disabled={availableEnvironments.length === 0}
          >
            {availableEnvironments.map(environment => (
              <option key={environment.id} value={environment.id}>
                {environment.display_name || environment.alias}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <FormField label={t('pages.tasks.create.taskPreset')}>
        <Select
          id={FIELD_IDS.taskPreset}
          value={selectedTaskPresetId}
          onChange={(e) => applyTaskPreset(e.target.value as TaskPresetId)}
        >
          {TASK_PRESET_OPTIONS.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {t(preset.labelKey)}
            </option>
          ))}
        </Select>
      </FormField>

      <fieldset className="space-y-2" aria-labelledby="task-create-researcher-type-label">
        <legend id="task-create-researcher-type-label" className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.tasks.create.researcherType')}
        </legend>
        <div className="flex flex-wrap gap-4 text-sm text-[var(--text-secondary)]">
          <label htmlFor={FIELD_IDS.researcherVanilla} className="flex items-center gap-2">
            <input
              id={FIELD_IDS.researcherVanilla}
              type="radio"
              name="researcher-type"
              value="vanilla"
              checked={researcherType === 'vanilla'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>{t('pages.tasks.create.researcherVanilla')}</span>
          </label>
          <label htmlFor={FIELD_IDS.researcherAris} className="flex items-center gap-2">
            <input
              id={FIELD_IDS.researcherAris}
              type="radio"
              name="researcher-type"
              value="aris-researcher"
              checked={researcherType === 'aris-researcher'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>{t('pages.tasks.create.researcherAris')}</span>
          </label>
        </div>
      </fieldset>

      <FormField label={t('pages.tasks.create.executionEngine')}>
        <Select
          id={FIELD_IDS.harnessEngine}
          value={harnessEngine}
          onChange={(e) => setHarnessEngine(e.target.value as HarnessEngine)}
        >
          <option value="claude-code">{t('pages.tasks.create.engineClaudeCode')}</option>
          <option value="agent-sdk">{t('pages.tasks.create.engineAgentSdk')}</option>
          <option value="codex-app-server">{t('pages.tasks.create.engineCodexAppServer')}</option>
        </Select>
      </FormField>

      {researcherType === 'vanilla' && (
        <div className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.tasks.skillsLabel')}
          </span>
          <TaskSkillPicker
            skills={availableSkills}
            selectedSkillIds={skills}
            onChange={setSkills}
          />
        </div>
      )}

      <FormField label={t('pages.tasks.titleLabel')}>
        <Input
          id={FIELD_IDS.title}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('pages.tasks.create.titlePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.tasks.create.promptLabel')}>
        <Textarea
          id={FIELD_IDS.prompt}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          placeholder={t('pages.tasks.create.promptPlaceholder')}
          required
        />
      </FormField>

      {selectedWorkspaceId === '' || selectedEnvironmentId === '' ? (
        <p className="rounded-lg border border-[var(--warning-border)] bg-[var(--warning-soft)] px-3 py-2 text-xs text-[var(--warning-foreground)]">
          {t('pages.tasks.create.missingBinding')}
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={!canSubmit}>
          {t('pages.tasks.createAction')}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  );
}
