import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button, Input, Select, SkillToggleGroup, Textarea } from '../../components/ui';
import { useT } from '../../i18n';
import type {
  EnvironmentRecord,
  ProjectRecord,
  SkillItem,
  TaskCreateRequest,
  WorkspaceRecord,
} from '../../types';
import type { ResearchAgentProfileSettings, TaskConfigurationPreset } from '../../settings';

interface Props {
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  projects?: ProjectRecord[];
  selectedWorkspaceId: string;
  selectedEnvironmentId: string;
  selectedProjectId?: string;
  selectedWorkspace: WorkspaceRecord | null;
  selectedEnvironment: EnvironmentRecord | null;
  draftDefaults: {
    title: string;
    task_input: string;
    researchAgentProfileId: string;
    taskConfigurationId: string;
  };
  researchAgentProfiles: ResearchAgentProfileSettings[];
  taskConfigurations: TaskConfigurationPreset[];
  availableSkills: SkillItem[];
  isSubmitting: boolean;
  createError: string | null;
  onSelectWorkspace: (workspaceId: string) => void;
  onSelectEnvironment: (environmentId: string) => void;
  onSelectProject?: (projectId: string) => void;
  onSubmit: (payload: TaskCreateRequest) => void;
  onClose?: () => void;
}

export default function TaskCreateForm({
  workspaces,
  environments,
  projects,
  selectedWorkspaceId,
  selectedEnvironmentId,
  selectedProjectId,
  selectedWorkspace,
  selectedEnvironment,
  draftDefaults,
  researchAgentProfiles,
  taskConfigurations,
  availableSkills,
  isSubmitting,
  createError,
  onSelectWorkspace,
  onSelectEnvironment,
  onSelectProject,
  onSubmit,
  onClose,
}: Props) {
  const t = useT();
  const defaultProfile = researchAgentProfiles.find(
    (profile) => profile.profileId === draftDefaults.researchAgentProfileId
  );
  const [draft, setDraft] = useState({
    title: draftDefaults.title,
    task_input: draftDefaults.task_input,
    task_profile: 'claude-code',
    researchAgentProfileId: draftDefaults.researchAgentProfileId,
    taskConfigurationId: draftDefaults.taskConfigurationId,
    skillModes: defaultProfile?.skillModes ?? {},
    researchGoal: '',
    context: '',
    constraints: '',
    deliverables: '',
    validationPlan: '',
    paperPath: '',
    scope: 'core-only',
    targetTable: '',
    budgetHours: 4,
    topic: '',
    seedPaperPath: '',
    depth: 3,
    ideaSource: '',
    validationScope: 'full',
  });
  const taskInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    taskInputRef.current?.focus();
  }, []);

  const selectedTaskConfiguration = taskConfigurations.find(
    (configuration) => configuration.configId === draft.taskConfigurationId
  );
  const selectedResearchAgentProfile = researchAgentProfiles.find(
    (profile) => profile.profileId === draft.researchAgentProfileId
  );
  const structuredPrompt = [
    ['Research goal', draft.researchGoal],
    ['Context', draft.context],
    ['Constraints', draft.constraints],
    ['Expected deliverables', draft.deliverables],
    ['Validation plan', draft.validationPlan],
  ]
    .filter(([, value]) => value.trim().length > 0)
    .map(([label, value]) => `${label}:\n${value.trim()}`)
    .join('\n\n');
  const effectiveTaskInput =
    selectedTaskConfiguration?.mode === 'structured_research'
      ? structuredPrompt || draft.task_input
      : selectedTaskConfiguration?.mode === 'reproduce_baseline' ||
          selectedTaskConfiguration?.mode === 'discover_ideas' ||
          selectedTaskConfiguration?.mode === 'validate_ideas'
        ? draft.task_input.trim() || `${selectedTaskConfiguration.label} task`
        : draft.task_input;
  const hasRequiredFields = (() => {
    if (selectedTaskConfiguration?.mode === 'reproduce_baseline') {
      return draft.paperPath.trim().length > 0;
    }
    if (selectedTaskConfiguration?.mode === 'discover_ideas') {
      return draft.topic.trim().length > 0;
    }
    if (selectedTaskConfiguration?.mode === 'validate_ideas') {
      return draft.ideaSource.trim().length > 0;
    }
    return effectiveTaskInput.trim().length > 0;
  })();
  const canCreate =
    selectedWorkspace !== null &&
    selectedEnvironment !== null &&
    hasRequiredFields &&
    !isSubmitting;

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!selectedWorkspace || !selectedEnvironment) {
          return;
        }

        const settings_json = selectedResearchAgentProfile?.settingsJson.trim()
          ? (JSON.parse(selectedResearchAgentProfile.settingsJson) as Record<string, unknown>)
          : null;
        onSubmit({
          project_id: selectedProjectId ?? 'default',
          workspace_id: selectedWorkspace.workspace_id,
          environment_id: selectedEnvironment.id,
          task_profile: draft.task_profile,
          task_input: effectiveTaskInput.trim(),
          title: draft.title.trim() || undefined,
          execution_engine: 'claude-code',
          auto_connect: true,
          research_agent_profile: selectedResearchAgentProfile
            ? {
                profile_id: selectedResearchAgentProfile.profileId,
                label: selectedResearchAgentProfile.label,
                system_prompt: selectedResearchAgentProfile.systemPrompt || null,
                skills: Object.keys(draft.skillModes).filter((id) => draft.skillModes[id] === 'enabled'),
                skills_prompt: selectedResearchAgentProfile.skillsPrompt || null,
                settings_json,
              }
            : null,
          task_configuration:
            selectedTaskConfiguration?.mode === 'structured_research'
              ? {
                  mode: 'structured_research',
                  template_id: selectedTaskConfiguration.configId,
                  template_vars: {
                    research_goal: draft.researchGoal,
                    context: draft.context,
                    constraints: draft.constraints,
                    deliverables: draft.deliverables,
                    validation_plan: draft.validationPlan,
                  },
                }
              : selectedTaskConfiguration?.mode === 'reproduce_baseline'
                ? {
                    mode: 'reproduce_baseline',
                    template_id: selectedTaskConfiguration.configId,
                    template_vars: {
                      paper_path: draft.paperPath,
                      scope: draft.scope,
                      target_table: draft.targetTable,
                      budget_hours: draft.budgetHours,
                    },
                  }
                : selectedTaskConfiguration?.mode === 'discover_ideas'
                  ? {
                      mode: 'discover_ideas',
                      template_id: selectedTaskConfiguration.configId,
                      template_vars: {
                        topic: draft.topic,
                        seed_paper_path: draft.seedPaperPath,
                        depth: draft.depth,
                        budget_hours: draft.budgetHours,
                      },
                    }
                  : selectedTaskConfiguration?.mode === 'validate_ideas'
                    ? {
                        mode: 'validate_ideas',
                        template_id: selectedTaskConfiguration.configId,
                        template_vars: {
                          idea_source: draft.ideaSource,
                          validation_scope: draft.validationScope,
                          budget_hours: draft.budgetHours,
                        },
                      }
                    : {
                        mode: 'raw_prompt',
                        template_id: selectedTaskConfiguration?.configId ?? null,
                        raw_prompt: draft.task_input.trim(),
                      },
        });
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-[var(--text)]">
            {t('pages.tasks.createTitle')}
          </h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {t('pages.tasks.createDescription')}
          </p>
        </div>
        {onClose ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            className="h-8 w-8 p-0 inline-flex items-center justify-center rounded-md"
            aria-label={t('pages.tasks.closeCreate')}
          >
            <X size={16} />
          </Button>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.workspaceLabel')}
          </span>
          <Select
            aria-label={t('pages.tasks.workspaceLabel')}
            value={selectedWorkspaceId}
            onChange={(event) => onSelectWorkspace(event.target.value)}
          >
            {workspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </option>
            ))}
          </Select>
        </label>

        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.environmentLabel')}
          </span>
          <Select
            aria-label={t('pages.tasks.environmentLabel')}
            value={selectedEnvironmentId}
            onChange={(event) => onSelectEnvironment(event.target.value)}
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {projects && projects.length > 0 ? (
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {'Project'}
          </span>
          <Select
            aria-label={'Project'}
            value={selectedProjectId ?? ''}
            onChange={(event) => onSelectProject?.(event.target.value)}
          >
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </Select>
        </label>
      ) : null}

      <label className="block space-y-2">
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {t('pages.tasks.profileLabel')}
        </span>
        <Select
          aria-label={t('pages.tasks.profileLabel')}
          value={draft.task_profile}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_profile: event.target.value }))
          }
        >
          <option value="claude-code">claude-code</option>
        </Select>
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.researchAgentLabel')}
          </span>
          <Select
            aria-label={t('pages.tasks.researchAgentLabel')}
            value={draft.researchAgentProfileId}
            onChange={(event) => {
              const nextId = event.target.value;
              const nextProfile = researchAgentProfiles.find(
                (profile) => profile.profileId === nextId
              );
              setDraft((current) => ({
                ...current,
                researchAgentProfileId: nextId,
                skillModes: nextProfile?.skillModes ?? {},
              }));
            }}
          >
            {researchAgentProfiles.map((profile) => (
              <option key={profile.profileId} value={profile.profileId}>
                {profile.label}
              </option>
            ))}
          </Select>
        </label>

        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.taskConfigurationLabel')}
          </span>
          <Select
            aria-label={t('pages.tasks.taskConfigurationLabel')}
            value={draft.taskConfigurationId}
            onChange={(event) =>
              setDraft((current) => ({ ...current, taskConfigurationId: event.target.value }))
            }
          >
            {taskConfigurations.map((configuration) => (
              <option key={configuration.configId} value={configuration.configId}>
                {configuration.label}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {availableSkills.length > 0 ? (
        <div className="space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.skillsLabel')}
          </span>
          <SkillToggleGroup
            skills={availableSkills}
            skillModes={draft.skillModes}
            onChange={(skillModes) => setDraft((current) => ({ ...current, skillModes }))}
          />
          {Object.keys(draft.skillModes).length > 0 && availableSkills.some((s) => s.dependencies.length > 0) ? (
            <p className="text-xs text-[var(--text-tertiary)]">
              {t('pages.tasks.skillDependenciesHint')}
            </p>
          ) : null}
        </div>
      ) : null}

      <label className="block space-y-2">
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {t('pages.tasks.titleLabel')}
        </span>
        <Input
          aria-label={t('pages.tasks.titleLabel')}
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
          placeholder={t('pages.tasks.optionalPlaceholder')}
        />
      </label>

      {selectedTaskConfiguration?.mode === 'structured_research' ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]/40 p-3">
          {[
            ['researchGoal', 'structuredResearchGoal'],
            ['context', 'structuredResearchContext'],
            ['constraints', 'structuredResearchConstraints'],
            ['deliverables', 'structuredResearchDeliverables'],
            ['validationPlan', 'structuredResearchValidationPlan'],
          ].map(([field, labelKey]) => (
            <label key={field} className="block space-y-2">
              <span className="text-xs font-medium text-[var(--text-secondary)]">
                {t(`pages.tasks.${labelKey}` as Parameters<typeof t>[0])}
              </span>
              <Textarea
                aria-label={t(`pages.tasks.${labelKey}` as Parameters<typeof t>[0])}
                value={String(draft[field as keyof typeof draft])}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, [field]: event.target.value }))
                }
                className="min-h-20"
              />
            </label>
          ))}
          <div className="rounded-lg bg-[var(--bg)] p-3 text-xs text-[var(--text-secondary)]">
            <p className="mb-2 font-medium text-[var(--text)]">
              {t('pages.tasks.generatedPromptPreview')}
            </p>
            <pre className="whitespace-pre-wrap font-mono">{structuredPrompt}</pre>
          </div>
        </div>
      ) : selectedTaskConfiguration?.mode === 'reproduce_baseline' ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]/40 p-3">
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.paperPathLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.paperPathLabel')}
              value={draft.paperPath}
              onChange={(e) => setDraft((c) => ({ ...c, paperPath: e.target.value }))}
              placeholder={t('pages.tasks.paperPathPlaceholder')}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.scopeLabel')}
            </span>
            <Select
              aria-label={t('pages.tasks.scopeLabel')}
              value={draft.scope}
              onChange={(e) => setDraft((c) => ({ ...c, scope: e.target.value }))}
            >
              <option value="core-only">core-only</option>
              <option value="full-suite">full-suite</option>
            </Select>
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.targetTableLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.targetTableLabel')}
              value={draft.targetTable}
              onChange={(e) => setDraft((c) => ({ ...c, targetTable: e.target.value }))}
              placeholder={t('pages.tasks.targetTablePlaceholder')}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.budgetHoursLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.budgetHoursLabel')}
              type="number"
              min={1}
              step={1}
              value={String(draft.budgetHours)}
              onChange={(e) => setDraft((c) => ({ ...c, budgetHours: Number(e.target.value) || 4 }))}
            />
          </label>
        </div>
      ) : selectedTaskConfiguration?.mode === 'discover_ideas' ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]/40 p-3">
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.researchTopicLabel')}
            </span>
            <Textarea
              aria-label={t('pages.tasks.researchTopicLabel')}
              value={draft.topic}
              onChange={(e) => setDraft((c) => ({ ...c, topic: e.target.value }))}
              className="min-h-20"
              placeholder={t('pages.tasks.researchTopicPlaceholder')}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.seedPaperPathLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.seedPaperPathLabel')}
              value={draft.seedPaperPath}
              onChange={(e) => setDraft((c) => ({ ...c, seedPaperPath: e.target.value }))}
              placeholder={t('pages.tasks.seedPaperPathPlaceholder')}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.depthLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.depthLabel')}
              type="number"
              min={1}
              max={10}
              step={1}
              value={String(draft.depth)}
              onChange={(e) => setDraft((c) => ({ ...c, depth: Number(e.target.value) || 3 }))}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.budgetHoursLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.budgetHoursLabel')}
              type="number"
              min={1}
              step={1}
              value={String(draft.budgetHours)}
              onChange={(e) => setDraft((c) => ({ ...c, budgetHours: Number(e.target.value) || 4 }))}
            />
          </label>
        </div>
      ) : selectedTaskConfiguration?.mode === 'validate_ideas' ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]/40 p-3">
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.ideaSourceLabel')}
            </span>
            <Textarea
              aria-label={t('pages.tasks.ideaSourceLabel')}
              value={draft.ideaSource}
              onChange={(e) => setDraft((c) => ({ ...c, ideaSource: e.target.value }))}
              className="min-h-20"
              placeholder={t('pages.tasks.ideaSourcePlaceholder')}
            />
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.validationScopeLabel')}
            </span>
            <Select
              aria-label={t('pages.tasks.validationScopeLabel')}
              value={draft.validationScope}
              onChange={(e) => setDraft((c) => ({ ...c, validationScope: e.target.value }))}
            >
              <option value="quick">quick</option>
              <option value="full">full</option>
            </Select>
          </label>
          <label className="block space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.budgetHoursLabel')}
            </span>
            <Input
              aria-label={t('pages.tasks.budgetHoursLabel')}
              type="number"
              min={1}
              step={1}
              value={String(draft.budgetHours)}
              onChange={(e) => setDraft((c) => ({ ...c, budgetHours: Number(e.target.value) || 4 }))}
            />
          </label>
        </div>
      ) : (
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {t('pages.tasks.taskInputLabel')}
          </span>
          <Textarea
            ref={taskInputRef}
            aria-label={t('pages.tasks.taskInputLabel')}
            value={draft.task_input}
            onChange={(event) =>
              setDraft((current) => ({ ...current, task_input: event.target.value }))
            }
            className="min-h-44"
            placeholder={t('pages.tasks.taskInputPlaceholder')}
          />
        </label>
      )}

      {selectedWorkspace ? (
        <p className="rounded-lg bg-[var(--bg-secondary)] px-3 py-2 text-xs text-[var(--text-secondary)]">
          {t('pages.tasks.defaultWorkdir')}{' '}
          <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-[var(--text)]">
            {selectedWorkspace.default_workdir ?? t('pages.tasks.unavailable')}
          </code>
        </p>
      ) : null}
      {createError ? <p className="text-sm text-[#ff3b30]">{createError}</p> : null}

      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-[var(--border)] pt-4">
        <Button
          type="button"
          variant="secondary"
          onClick={() =>
            setDraft({
              title: draftDefaults.title,
              task_input: draftDefaults.task_input,
              task_profile: 'claude-code',
              researchAgentProfileId: draftDefaults.researchAgentProfileId,
              taskConfigurationId: draftDefaults.taskConfigurationId,
              skillModes: defaultProfile?.skillModes ?? {},
              researchGoal: '',
              context: '',
              constraints: '',
              deliverables: '',
              validationPlan: '',
              paperPath: '',
              scope: 'core-only',
              targetTable: '',
              budgetHours: 4,
              topic: '',
              seedPaperPath: '',
              depth: 3,
              ideaSource: '',
              validationScope: 'full',
            })
          }
        >
          {t('pages.tasks.resetDraft')}
        </Button>

        <Button type="submit" disabled={!canCreate}>
          {isSubmitting ? t('pages.tasks.creatingAction') : t('pages.tasks.createAction')}
        </Button>
      </div>
    </form>
  );
}
