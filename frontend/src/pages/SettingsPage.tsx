import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  FormField,
  Input,
  PageHeader,
  SectionCard,
  SectionHeader,
  Select,
  SkillToggleGroup,
  Textarea,
} from '../components/ui';
import { PageShell, SectionStack } from '../components/layout';
import { EnvironmentSelectorPanel, useEnvironmentSelection } from '../components';
import { getDeploymentVersion, getFrontendBuildVersion, getEnvironments, getSkills, getWorkspaces, getSkillDetail, previewSkillSettings, importSkill, getSkillRegistries, installSkillRegistry, updateSkillRegistry, getSearchSettings, updateSearchSettings } from '../api';
import { changePassword } from '../api/endpoints';
import { useT } from '../i18n';
import {
  clampEditorFontSize,
  clampTerminalFontSize,
  maxEditorFontSize,
  maxTerminalFontSize,
  minEditorFontSize,
  minTerminalFontSize,
  useSettings,
} from '../settings';
import type {
  DefaultRoute,
  EnvironmentTaskDefaults,
  ExecutionEngineId,
  ResearchAgentProfileSettings,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from '../settings';
import type { EnvironmentRecord, SkillItem, SkillDetail, SkillImportRequest, SkillPreview, SkillRegistryItem, SearchBackendItem } from '../types';
import { UsersTab } from './settings/UsersTab';
import { EnvAccessTab } from './settings/EnvAccessTab';
import { CollaboratorsTab } from './settings/CollaboratorsTab';
import { LlmProvidersTab } from './settings/LlmProvidersTab';
import MonitoringTab from './settings/MonitoringTab';
import { useAuth } from '../contexts/AuthContext';

interface GeneralDraftState {
  defaultRoute: DefaultRoute;
  terminalFontSize: string;
  editorFontSize: string;
  editorFontFamily: string;
}

interface GeneralPreferencesSectionProps {
  savedGeneral: WebUiSettingsDocument['general'];
  onSave: (general: WebUiSettingsDocument['general']) => void;
  onReset: () => void;
}

interface EnvironmentDefaultsCardProps {
  environment: EnvironmentRecord;
  savedDefaults: EnvironmentTaskDefaults;
  onSave: (defaults: EnvironmentTaskDefaults) => void;
  onReset: () => void;
}

interface TaskConfigurationSectionProps {
  taskConfiguration: TaskConfigurationSettings;
  availableSkills: SkillItem[];
  onSaveTaskConfigurationSettings: (settings: TaskConfigurationSettings) => void;
  onResetTaskConfigurationSettings: () => void;
}

interface ProjectDefaultsSectionProps {
  environments: EnvironmentRecord[];
  taskConfiguration: TaskConfigurationSettings;
  savedDefaultEnvironmentId: string | null;
  isLoading: boolean;
  loadError: string | null;
  getProjectEnvironmentDefaults: (environmentId: string | null) => EnvironmentTaskDefaults;
  saveProjectDefaultEnvironment: (environmentId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (environmentId: string) => void;
}

function hasEnvironmentDefaultChanges(
  left: EnvironmentTaskDefaults,
  right: EnvironmentTaskDefaults
): boolean {
  return (
    left.titleTemplate !== right.titleTemplate ||
    left.taskInputTemplate !== right.taskInputTemplate ||
    left.researchAgentProfileId !== right.researchAgentProfileId ||
    left.taskConfigurationId !== right.taskConfigurationId
  );
}

function GeneralPreferencesSection({
  savedGeneral,
  onSave,
  onReset,
}: GeneralPreferencesSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState<GeneralDraftState>({
    defaultRoute: savedGeneral.defaultRoute,
    terminalFontSize: String(savedGeneral.terminal.fontSize),
    editorFontSize: String(savedGeneral.editor.fontSize),
    editorFontFamily: savedGeneral.editor.fontFamily,
  });
  const clampedTerminalFontSize = clampTerminalFontSize(Number.parseInt(draft.terminalFontSize, 10));
  const clampedEditorFontSize = clampEditorFontSize(Number.parseInt(draft.editorFontSize, 10));
  const hasChanges =
    draft.defaultRoute !== savedGeneral.defaultRoute ||
    clampedTerminalFontSize !== savedGeneral.terminal.fontSize ||
    clampedEditorFontSize !== savedGeneral.editor.fontSize ||
    draft.editorFontFamily !== savedGeneral.editor.fontFamily;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.general.title')}
          description={t('pages.settings.general.description')}
        />
      }
    >

      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.general.defaultRouteLabel')}>
          <Select
            aria-label={t('pages.settings.general.defaultRouteLabel')}
            value={draft.defaultRoute}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                defaultRoute: event.target.value as DefaultRoute,
              }))
            }
          >
            <option value="terminal">{t('pages.settings.routes.terminal')}</option>
            <option value="tasks">{t('pages.settings.routes.tasks')}</option>
            <option value="workspaces">{t('pages.settings.routes.workspaces')}</option>
            <option value="environments">{t('pages.settings.routes.environments')}</option>
          </Select>
        </FormField>

        <FormField label={t('pages.settings.general.terminalFontSizeLabel')}>
          <Input
            aria-label={t('pages.settings.general.terminalFontSizeLabel')}
            type="number"
            min={minTerminalFontSize}
            max={maxTerminalFontSize}
            step={1}
            value={draft.terminalFontSize}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                terminalFontSize: event.target.value,
              }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.general.editorFontSizeLabel')}>
          <Input
            aria-label={t('pages.settings.general.editorFontSizeLabel')}
            type="number"
            min={minEditorFontSize}
            max={maxEditorFontSize}
            step={1}
            value={draft.editorFontSize}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                editorFontSize: event.target.value,
              }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.general.editorFontFamilyLabel')}>
          <Input
            aria-label={t('pages.settings.general.editorFontFamilyLabel')}
            type="text"
            value={draft.editorFontFamily}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                editorFontFamily: event.target.value,
              }))
            }
          />
        </FormField>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>
          {t('pages.settings.general.terminalFontSizeHelp', {
            min: minTerminalFontSize,
            max: maxTerminalFontSize,
            current: clampedTerminalFontSize,
          })}
          {' / '}
          {t('pages.settings.general.editorFontSizeHelp', {
            min: minEditorFontSize,
            max: maxEditorFontSize,
            current: clampedEditorFontSize,
          })}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onReset}>
            {t('common.reset')}
          </Button>
          <Button
            onClick={() =>
              onSave({
                defaultRoute: draft.defaultRoute,
                terminal: {
                  fontSize: clampedTerminalFontSize,
                },
                editor: {
                  fontSize: clampedEditorFontSize,
                  fontFamily: draft.editorFontFamily || 'monospace',
                },
                appearance: savedGeneral.appearance,
              })
            }
            disabled={!hasChanges}
          >
            {t('common.saveChanges')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function TaskConfigurationSection({
  taskConfiguration,
  availableSkills,
  onSaveTaskConfigurationSettings,
  onResetTaskConfigurationSettings,
}: TaskConfigurationSectionProps) {
  const t = useT();
  const settingsContext = useSettings();
  const [profileDraft, setProfileDraft] = useState<ResearchAgentProfileSettings>(
    taskConfiguration.researchAgentProfiles.find(
      (p) => p.profileId === taskConfiguration.defaultResearchAgentProfileId
    ) ?? taskConfiguration.researchAgentProfiles[0] ?? {
      profileId: 'claude-code-default',
      label: 'Claude Code Default',
      systemPrompt: '',
      skills: [],
      skillModes: {},
      skillsPrompt: '',
      settingsJson: '',
      apiBaseUrl: '',
      apiKey: '',
      defaultOpusModel: '',
      defaultSonnetModel: '',
      defaultHaikuModel: '',
      envOverrides: '',
      codexBaseUrl: '',
      codexApiKey: '',
      codexModel: '',
      codexAppServerCommand: '',
      codexApprovalPolicy: '',
      codexConfigToml: '',
      codexAuthJson: '',
      codexConfigTomlSource: 'custom',
      codexAuthJsonSource: 'custom',
    }
  );
  const [defaultProfileId, setDefaultProfileId] = useState(
    taskConfiguration.defaultResearchAgentProfileId
  );
  const [defaultConfigId, setDefaultConfigId] = useState(taskConfiguration.defaultTaskConfigurationId);

  useEffect(() => {
    const nextProfile = taskConfiguration.researchAgentProfiles.find(
      (p) => p.profileId === taskConfiguration.defaultResearchAgentProfileId
    );
    // Reset draft when the external server configuration changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfileDraft(
      nextProfile ?? taskConfiguration.researchAgentProfiles[0] ?? {
        profileId: 'claude-code-default',
        label: 'Claude Code Default',
        systemPrompt: '',
        skills: [],
        skillModes: {},
        skillsPrompt: '',
        settingsJson: '',
        apiBaseUrl: '',
        apiKey: '',
        defaultOpusModel: '',
        defaultSonnetModel: '',
        defaultHaikuModel: '',
        envOverrides: '',
        codexBaseUrl: '',
        codexApiKey: '',
        codexModel: '',
        codexAppServerCommand: '',
        codexApprovalPolicy: '',
        codexConfigToml: '',
        codexAuthJson: '',
        codexConfigTomlSource: 'custom',
        codexAuthJsonSource: 'custom',
      }
    );
    setDefaultProfileId(taskConfiguration.defaultResearchAgentProfileId);
    setDefaultConfigId(taskConfiguration.defaultTaskConfigurationId);
  }, [taskConfiguration]);

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.taskConfiguration.title')}
          description={t('pages.settings.taskConfiguration.description')}
        />
      }
    >

      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.taskConfiguration.executionEngineLabel')}>
          <Select
            aria-label={t('pages.settings.taskConfiguration.executionEngineLabel')}
            value={taskConfiguration.defaultExecutionEngineId}
            onChange={(event) =>
              onSaveTaskConfigurationSettings({
                ...taskConfiguration,
                defaultExecutionEngineId: event.target.value as ExecutionEngineId,
              })
            }
          >
            <option value="claude-code">{t('pages.settings.engine.claudeCode')}</option>
            <option value="agent-sdk">{t('pages.settings.engine.claudeAgent')}</option>
            <option value="codex-app-server">{t('pages.settings.engine.codexAppServer')}</option>
          </Select>
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}>
          <Select
            aria-label={t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}
            value={defaultConfigId}
            onChange={(event) => setDefaultConfigId(event.target.value)}
          >
            {taskConfiguration.taskConfigurations.map((config) => (
              <option key={config.configId} value={config.configId}>
                {config.label}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <FormField label={t('pages.settings.taskConfiguration.defaultResearchAgentLabel')}>
          <Select
            aria-label={t('pages.settings.taskConfiguration.defaultResearchAgentLabel')}
            value={defaultProfileId}
            onChange={(event) => {
              const nextId = event.target.value;
              setDefaultProfileId(nextId);
              const nextProfile = taskConfiguration.researchAgentProfiles.find(
                (profile) => profile.profileId === nextId
              );
              if (nextProfile) {
                setProfileDraft(nextProfile);
              }
            }}
          >
            {taskConfiguration.researchAgentProfiles.map((profile) => (
              <option key={profile.profileId} value={profile.profileId}>
                {profile.label}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.profileLabel')}>
          <Input
            aria-label={t('pages.settings.taskConfiguration.profileLabel')}
            value={profileDraft.label}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, label: event.target.value }))
            }
          />
        </FormField>

        <FormField label={t('pages.settings.taskConfiguration.systemPromptLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.systemPromptLabel')}
            value={profileDraft.systemPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, systemPrompt: event.target.value }))
            }
            className="min-h-24"
          />
        </FormField>

        {availableSkills.length > 0 ? (
          <div className="space-y-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              {t('pages.settings.taskConfiguration.skillsLabel')}
            </span>
            <SkillToggleGroup
              skills={availableSkills}
              skillModes={profileDraft.skillModes}
              onChange={(skillModes) =>
                setProfileDraft((current) => ({
                  ...current,
                  skillModes,
                  skills: Object.entries(skillModes)
                    .filter(([, mode]) => mode === 'enabled')
                    .map(([skillId]) => skillId),
                }))
              }
            />
            <p className="text-xs text-[var(--text-tertiary)]">
              {t('pages.settings.taskConfiguration.skillsDescription')}
            </p>
          </div>
        ) : null}

        <FormField label={t('pages.settings.taskConfiguration.skillsPromptLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.skillsPromptLabel')}
            value={profileDraft.skillsPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, skillsPrompt: event.target.value }))
            }
            className="min-h-16"
          />
        </FormField>

        {taskConfiguration.defaultExecutionEngineId === 'agent-sdk' && (
          <>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
                  <Select
                    aria-label={t('pages.settings.llmProviders.fillFromProvider')}
                    value=""
                    onChange={(event) => {
                      const providerId = event.target.value;
                      if (!providerId) return;
                      const provider = settingsContext.settings.llmProviders.find((p) => p.id === providerId);
                      if (!provider) return;
                      setProfileDraft((current) => ({
                        ...current,
                        apiBaseUrl: provider.baseUrl,
                        apiKey: provider.apiKey,
                        defaultOpusModel:
                          provider.format === 'anthropic'
                            ? (provider.opusModel ?? current.defaultOpusModel)
                            : (provider.defaultModel ?? current.defaultOpusModel),
                        defaultSonnetModel:
                          provider.format === 'anthropic'
                            ? (provider.sonnetModel ?? current.defaultSonnetModel)
                            : (provider.defaultModel ?? current.defaultSonnetModel),
                        defaultHaikuModel:
                          provider.format === 'anthropic'
                            ? (provider.haikuModel ?? current.defaultHaikuModel)
                            : (provider.defaultModel ?? current.defaultHaikuModel),
                      }));
                    }}
                  >
                    <option value="">{t('pages.settings.llmProviders.customOption')}</option>
                    {settingsContext.settings.llmProviders
                      .filter((p) => p.format === 'anthropic')
                      .map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                  </Select>
                </FormField>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label={t('pages.settings.taskConfiguration.apiBaseUrlLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.apiBaseUrlLabel')}
                  value={profileDraft.apiBaseUrl}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, apiBaseUrl: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.apiBaseUrl')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.apiKeyLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.apiKeyLabel')}
                  type="password"
                  value={profileDraft.apiKey}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, apiKey: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.apiKey')}
                />
              </FormField>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField label={t('pages.settings.taskConfiguration.defaultOpusModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultOpusModelLabel')}
                  value={profileDraft.defaultOpusModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultOpusModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.opusModel')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.defaultSonnetModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultSonnetModelLabel')}
                  value={profileDraft.defaultSonnetModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultSonnetModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.sonnetModel')}
                />
              </FormField>
              <FormField label={t('pages.settings.taskConfiguration.defaultHaikuModelLabel')}>
                <Input
                  aria-label={t('pages.settings.taskConfiguration.defaultHaikuModelLabel')}
                  value={profileDraft.defaultHaikuModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, defaultHaikuModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.taskConfiguration.placeholders.haikuModel')}
                />
              </FormField>
            </div>
            <FormField label={t('pages.settings.taskConfiguration.envOverridesLabel')}>
              <Textarea
                aria-label={t('pages.settings.taskConfiguration.envOverridesLabel')}
                value={profileDraft.envOverrides}
                onChange={(event) =>
                  setProfileDraft((current) => ({ ...current, envOverrides: event.target.value }))
                }
                className="min-h-20 font-mono text-xs"
                placeholder={t('pages.settings.taskConfiguration.placeholders.envOverrides')}
              />
            </FormField>
          </>
        )}

        {taskConfiguration.defaultExecutionEngineId === 'codex-app-server' && (
          <>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <FormField label={t('pages.settings.llmProviders.fillFromProvider')}>
                  <Select
                    aria-label={t('pages.settings.llmProviders.fillFromProvider')}
                    value=""
                    onChange={(event) => {
                      const providerId = event.target.value;
                      if (!providerId) return;
                      const provider = settingsContext.settings.llmProviders.find((p) => p.id === providerId);
                      if (!provider) return;
                      setProfileDraft((current) => ({
                        ...current,
                        codexBaseUrl: provider.baseUrl,
                        codexApiKey: provider.apiKey,
                        codexModel: provider.defaultModel ?? current.codexModel,
                      }));
                    }}
                  >
                    <option value="">{t('pages.settings.llmProviders.customOption')}</option>
                    {settingsContext.settings.llmProviders
                      .filter((p) => p.format === 'openai-responses')
                      .map((provider) => (
                        <option key={provider.id} value={provider.id}>
                          {provider.name}
                        </option>
                      ))}
                  </Select>
                </FormField>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label={t('pages.settings.codex.baseUrl')}>
                <Input
                  aria-label={t('pages.settings.codex.baseUrl')}
                  value={profileDraft.codexBaseUrl}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexBaseUrl: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.baseUrl')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.apiKey')}>
                <Input
                  aria-label={t('pages.settings.codex.apiKey')}
                  type="password"
                  value={profileDraft.codexApiKey}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexApiKey: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.apiKey')}
                />
              </FormField>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField label={t('pages.settings.codex.model')}>
                <Input
                  aria-label={t('pages.settings.codex.model')}
                  value={profileDraft.codexModel}
                  onChange={(event) =>
                    setProfileDraft((current) => ({ ...current, codexModel: event.target.value }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.model')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.command')}>
                <Input
                  aria-label={t('pages.settings.codex.command')}
                  value={profileDraft.codexAppServerCommand}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      codexAppServerCommand: event.target.value,
                    }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.command')}
                />
              </FormField>
              <FormField label={t('pages.settings.codex.approval')}>
                <Input
                  aria-label={t('pages.settings.codex.approval')}
                  value={profileDraft.codexApprovalPolicy}
                  onChange={(event) =>
                    setProfileDraft((current) => ({
                      ...current,
                      codexApprovalPolicy: event.target.value,
                    }))
                  }
                  placeholder={t('pages.settings.codex.placeholders.approval')}
                />
              </FormField>
            </div>
            <FormField label={t('pages.settings.codex.config')}>
              <Textarea
                aria-label={t('pages.settings.codex.config')}
                value={profileDraft.codexConfigToml}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    codexConfigToml: event.target.value,
                    codexConfigTomlSource: 'custom',
                  }))
                }
                className="min-h-24 font-mono text-xs"
                placeholder={t('pages.settings.codex.placeholders.config')}
              />
            </FormField>
            <FormField label={t('pages.settings.codex.auth')}>
              <Textarea
                aria-label={t('pages.settings.codex.auth')}
                value={profileDraft.codexAuthJson}
                onChange={(event) =>
                  setProfileDraft((current) => ({
                    ...current,
                    codexAuthJson: event.target.value,
                    codexAuthJsonSource: 'custom',
                  }))
                }
                className="min-h-24 font-mono text-xs"
                placeholder={t('pages.settings.codex.placeholders.auth')}
              />
            </FormField>
          </>
        )}

        <FormField label={t('pages.settings.taskConfiguration.settingsJsonLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.settingsJsonLabel')}
            value={profileDraft.settingsJson}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, settingsJson: event.target.value }))
            }
            className="min-h-28 font-mono text-xs"
          />
        </FormField>
      </div>

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onResetTaskConfigurationSettings}>
          {t('common.reset')}
        </Button>
        <Button
          onClick={() => {
            const nextProfiles = taskConfiguration.researchAgentProfiles.some(
              (p) => p.profileId === profileDraft.profileId
            )
              ? taskConfiguration.researchAgentProfiles.map((p) =>
                  p.profileId === profileDraft.profileId ? profileDraft : p
                )
              : [...taskConfiguration.researchAgentProfiles, profileDraft];
            onSaveTaskConfigurationSettings({
              ...taskConfiguration,
              researchAgentProfiles: nextProfiles,
              defaultResearchAgentProfileId: defaultProfileId,
              defaultTaskConfigurationId: defaultConfigId,
            });
          }}
        >
          {t('common.saveChanges')}
        </Button>
      </div>
    </SectionCard>
  );
}

function EnvironmentDefaultsCard({
  environment,
  savedDefaults,
  taskConfiguration,
  onSave,
  onReset,
}: EnvironmentDefaultsCardProps & { taskConfiguration: TaskConfigurationSettings }) {
  const t = useT();
  const [draft, setDraft] = useState<EnvironmentTaskDefaults>(savedDefaults);
  const hasChanges = hasEnvironmentDefaultChanges(draft, savedDefaults);

  return (
    <SectionCard
      collapsible
      defaultExpanded={false}
      header={
        <SectionHeader
          title={`${environment.alias} · ${environment.display_name}`}
          description={t('pages.settings.project.environmentCardDescription')}
          size="sm"
        />
      }
      className="space-y-4 p-5"
    >

      <FormField label={t('pages.settings.project.titleTemplateLabel')}>
        <Input
          aria-label={`${environment.alias} ${t('pages.settings.project.titleTemplateLabel')}`}
          value={draft.titleTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              titleTemplate: event.target.value,
            }))
          }
          placeholder={t('pages.settings.project.titleTemplatePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.settings.project.taskInputTemplateLabel')}>
        <Textarea
          aria-label={`${environment.alias} ${t('pages.settings.project.taskInputTemplateLabel')}`}
          value={draft.taskInputTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskInputTemplate: event.target.value,
            }))
          }
          className="min-h-32"
          placeholder={t('pages.settings.project.taskInputTemplatePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.settings.project.researchAgentDefaultLabel')}>
        <Select
          aria-label={`${environment.alias} ${t('pages.settings.project.researchAgentDefaultLabel')}`}
          value={draft.researchAgentProfileId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              researchAgentProfileId: event.target.value,
            }))
          }
        >
          {taskConfiguration.researchAgentProfiles.map((profile) => (
            <option key={profile.profileId} value={profile.profileId}>
              {profile.label}
            </option>
          ))}
        </Select>
      </FormField>

      <FormField label={t('pages.settings.project.taskConfigurationDefaultLabel')}>
        <Select
          aria-label={`${environment.alias} ${t('pages.settings.project.taskConfigurationDefaultLabel')}`}
          value={draft.taskConfigurationId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskConfigurationId: event.target.value,
            }))
          }
        >
          {taskConfiguration.taskConfigurations.map((config) => (
            <option key={config.configId} value={config.configId}>
              {config.label}
            </option>
          ))}
        </Select>
      </FormField>

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onReset}>
          {t('common.reset')}
        </Button>
        <Button onClick={() => onSave(draft)} disabled={!hasChanges}>
          {t('common.saveChanges')}
        </Button>
      </div>
    </SectionCard>
  );
}

function ProjectDefaultsSection({
  environments,
  taskConfiguration,
  savedDefaultEnvironmentId,
  isLoading,
  loadError,
  getProjectEnvironmentDefaults,
  saveProjectDefaultEnvironment,
  saveProjectEnvironmentDefaults,
  resetProjectEnvironmentDefaults,
}: ProjectDefaultsSectionProps) {
  const t = useT();
  const [defaultEnvironmentDraft, setDefaultEnvironmentDraft] = useState<string>(
    savedDefaultEnvironmentId ?? ''
  );
  const persistedProjectDefaultEnvironmentId = savedDefaultEnvironmentId ?? '';
  const hasProjectDefaultChanges = defaultEnvironmentDraft !== persistedProjectDefaultEnvironmentId;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.project.title')}
          description={t('pages.settings.project.description')}
        />
      }
    >

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <FormField label={t('pages.settings.project.defaultEnvironmentLabel')}>
          <Select
            aria-label={t('pages.settings.project.defaultEnvironmentLabel')}
            value={defaultEnvironmentDraft}
            onChange={(event) => setDefaultEnvironmentDraft(event.target.value)}
            disabled={environments.length === 0}
          >
            <option value="">{t('pages.settings.project.defaultEnvironmentEmpty')}</option>
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </Select>
        </FormField>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.settings.project.defaultEnvironmentHelp')}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => saveProjectDefaultEnvironment(null)}>
              {t('common.reset')}
            </Button>
            <Button
              onClick={() => saveProjectDefaultEnvironment(defaultEnvironmentDraft || null)}
              disabled={!hasProjectDefaultChanges}
            >
              {t('common.saveChanges')}
            </Button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('common.loading')}
        </p>
      ) : null}
      {loadError ? <p className="text-sm text-[#ff3b30]">{loadError}</p> : null}
      {environments.length === 0 && !isLoading ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('pages.settings.project.noEnvironments')}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {environments.map((environment) => {
          const savedDefaults = getProjectEnvironmentDefaults(environment.id);
          return (
            <EnvironmentDefaultsCard
              key={`${environment.id}:${savedDefaults.titleTemplate}:${savedDefaults.taskInputTemplate}:${savedDefaults.researchAgentProfileId}:${savedDefaults.taskConfigurationId}`}
              environment={environment}
              savedDefaults={savedDefaults}
              taskConfiguration={taskConfiguration}
              onSave={(defaults) => saveProjectEnvironmentDefaults(environment.id, defaults)}
              onReset={() => resetProjectEnvironmentDefaults(environment.id)}
            />
          );
        })}
      </div>
    </SectionCard>
  );
}

interface AppearanceSectionProps {
  savedAppearance: WebUiSettingsDocument['general']['appearance'];
  onSave: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  onReset: () => void;
}

function AppearanceSection({ savedAppearance, onSave, onReset }: AppearanceSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState(savedAppearance);
  const hasChanges = draft.fontFamily !== savedAppearance.fontFamily;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.appearance.title')}
          description={t('pages.settings.appearance.description')}
        />
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.appearance.fontFamilyLabel')}>
          <Select
            aria-label={t('pages.settings.appearance.fontFamilyLabel')}
            value={draft.fontFamily}
            onChange={(event) =>
              setDraft({ fontFamily: event.target.value as 'sans-serif' | 'serif' })
            }
          >
            <option value="sans-serif">{t('pages.settings.appearance.sansSerif')}</option>
            <option value="serif">{t('pages.settings.appearance.serif')}</option>
          </Select>
        </FormField>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>{t('pages.settings.appearance.previewHint')}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onReset}>
            {t('common.reset')}
          </Button>
          <Button onClick={() => onSave(draft)} disabled={!hasChanges}>
            {t('common.saveChanges')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function SearchBackendSection() {
  const t = useT();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['searchSettings'],
    queryFn: getSearchSettings,
  });
  const mutation = useMutation({
    mutationFn: updateSearchSettings,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['searchSettings'] }); },
  });

  const activeBackend = data?.active_backend ?? 'cc-web-mcp';
  const autoStart = data?.auto_start_mcp_servers ?? ['kindly-web-search', 'cc-web-mcp'];
  const backends = data?.available_backends ?? [];

  const toggleAutoStart = (id: string) => {
    const next = autoStart.includes(id)
      ? autoStart.filter((s: string) => s !== id)
      : [...autoStart, id];
    mutation.mutate({ auto_start_mcp_servers: next });
  };

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.searchBackend.title')}
          description={t('pages.settings.searchBackend.description')}
        />
      }
    >
      <div className="space-y-4">
        <FormField label={t('pages.settings.searchBackend.activeBackend')}>
          <Select
            aria-label={t('pages.settings.searchBackend.activeBackend')}
            value={activeBackend}
            disabled={isLoading || mutation.isPending}
            onChange={(e) => mutation.mutate({ active_backend: e.target.value })}
          >
            {backends.map((b: SearchBackendItem) => (
              <option key={b.id} value={b.id}>
                {b.display_name}
              </option>
            ))}
          </Select>
        </FormField>

        <div>
          <p className="mb-2 text-sm font-medium text-[var(--text)]">
            {t('pages.settings.searchBackend.autoStart')}
          </p>
          <p className="mb-3 text-xs text-[var(--text-secondary)]">
            {t('pages.settings.searchBackend.autoStartHint')}
          </p>
          <div className="space-y-2">
            {backends
              .filter((b: SearchBackendItem) => b.requires_mcp)
              .map((b: SearchBackendItem) => (
                <label key={b.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={autoStart.includes(b.id)}
                    disabled={mutation.isPending}
                    onChange={() => toggleAutoStart(b.id)}
                    className="rounded border-[var(--border)]"
                  />
                  <span>{b.display_name}</span>
                  <span className="text-[var(--text-secondary)]">— {b.description}</span>
                </label>
              ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

interface SkillRepositorySectionProps {
  availableSkills: SkillItem[];
}

function SkillRepositorySection({ availableSkills }: SkillRepositorySectionProps) {
  const t = useT();
  const queryClient = useQueryClient();
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importSource, setImportSource] = useState<'git' | 'local'>('git');
  const [importUrl, setImportUrl] = useState('');
  const [importPath, setImportPath] = useState('');
  const [importSkillId, setImportSkillId] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [showDirtyConfirm, setShowDirtyConfirm] = useState(false);
  const [pendingRegistryId, setPendingRegistryId] = useState<string | null>(null);

  const detailQuery = useQuery<SkillDetail>({
    queryKey: ['skillDetail', selectedSkillId],
    queryFn: () => getSkillDetail(selectedSkillId!),
    enabled: !!selectedSkillId,
  });

  const previewQuery = useQuery<SkillPreview>({
    queryKey: ['skillPreview', selectedSkillId],
    queryFn: () => previewSkillSettings(selectedSkillId!),
    enabled: !!selectedSkillId,
  });

  const importMutation = useMutation({
    mutationFn: importSkill,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setShowImport(false);
      setImportUrl('');
      setImportPath('');
      setImportSkillId('');
      setImportError(null);
    },
    onError: (err: Error) => setImportError(err.message),
  });

  const registriesQuery = useQuery({
    queryKey: ['skillRegistries'],
    queryFn: getSkillRegistries,
  });

  const installRegistryMutation = useMutation({
    mutationFn: installSkillRegistry,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skillRegistries'] });
      queryClient.invalidateQueries({ queryKey: ['skills'] });
    },
    onError: (err: Error) => {
      alert(err.message);
    },
  });

  const updateRegistryMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) =>
      updateSkillRegistry(id, { force }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skillRegistries'] });
      queryClient.invalidateQueries({ queryKey: ['skills'] });
      setShowDirtyConfirm(false);
      setPendingRegistryId(null);
    },
    onError: (err: unknown) => {
      const status = typeof err === 'object' && err !== null && 'status' in err ? (err as { status?: number }).status : undefined;
      if (status === 409) {
        setShowDirtyConfirm(true);
      } else {
        alert(err instanceof Error ? err.message : t('pages.settings.llmProviders.updateFailed'));
        setShowDirtyConfirm(false);
        setPendingRegistryId(null);
      }
    },
  });

  const handleImportSubmit = () => {
    setImportError(null);
    const payload: SkillImportRequest = {
      source: importSource,
      url: importSource === 'git' ? importUrl || null : null,
      local_path: importSource === 'local' ? importPath || null : null,
      skill_id: importSkillId || null,
    };
    importMutation.mutate(payload);
  };

  const getInjectModeBadgeClasses = (mode: string) => {
    switch (mode) {
      case 'auto':
        return 'rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800';
      case 'prompt_only':
        return 'rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800';
      case 'disabled':
        return 'rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600';
      default:
        return 'rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600';
    }
  };

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.skillRepository.title')}
          description={t('pages.settings.skillRepository.description')}
        />
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button onClick={() => setShowImport((current) => !current)}>
          {t('pages.settings.skillRepository.importSkill')}
        </Button>
        {(registriesQuery.data?.items ?? []).map((registry: SkillRegistryItem) => (
          <div key={registry.registry_id} className="flex items-center gap-2">
            {!registry.installed ? (
              <Button
                onClick={() => installRegistryMutation.mutate(registry.registry_id)}
                disabled={installRegistryMutation.isPending}
              >
                {installRegistryMutation.isPending
                  ? t('pages.settings.codex.installing', { name: registry.display_name })
                  : t('pages.settings.codex.install', { name: registry.display_name })}
              </Button>
            ) : registry.has_update ? (
              <Button
                onClick={() => {
                  setPendingRegistryId(registry.registry_id);
                  updateRegistryMutation.mutate({ id: registry.registry_id, force: false });
                }}
                disabled={updateRegistryMutation.isPending}
              >
                {updateRegistryMutation.isPending
                  ? t('pages.settings.codex.updating')
                  : t('pages.settings.codex.update', { name: registry.display_name })}
              </Button>
            ) : (
              <Button disabled>
                {t('pages.settings.codex.installed', { name: registry.display_name })}
              </Button>
            )}
          </div>
        ))}
      </div>

      {showImport && (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h4 className="text-sm font-medium text-[var(--text-primary)]">
            {t('pages.settings.skillRepository.importTitle')}
          </h4>

          <FormField label={t('pages.settings.skillRepository.sourceLabel')}>
            <Select
              aria-label={t('pages.settings.skillRepository.sourceLabel')}
              value={importSource}
              onChange={(event) => setImportSource(event.target.value as 'git' | 'local')}
            >
              <option value="git">{t('pages.settings.skillRepository.gitSource')}</option>
              <option value="local">{t('pages.settings.skillRepository.localSource')}</option>
            </Select>
          </FormField>

          {importSource === 'git' ? (
            <FormField label={t('pages.settings.skillRepository.urlLabel')}>
              <Input
                aria-label={t('pages.settings.skillRepository.urlLabel')}
                type="text"
                value={importUrl}
                onChange={(event) => setImportUrl(event.target.value)}
                placeholder={t('pages.settings.skillRepository.placeholders.url')}
              />
            </FormField>
          ) : (
            <FormField label={t('pages.settings.skillRepository.pathLabel')}>
              <Input
                aria-label={t('pages.settings.skillRepository.pathLabel')}
                type="text"
                value={importPath}
                onChange={(event) => setImportPath(event.target.value)}
                placeholder={t('pages.settings.skillRepository.placeholders.path')}
              />
            </FormField>
          )}

          <FormField label={t('pages.settings.skillRepository.skillIdOverrideLabel')}>
            <Input
              aria-label={t('pages.settings.skillRepository.skillIdOverrideLabel')}
              type="text"
              value={importSkillId}
              onChange={(event) => setImportSkillId(event.target.value)}
            />
          </FormField>

          {importError ? <p className="text-sm text-[#ff3b30]">{importError}</p> : null}

          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setShowImport(false)}>
              {t('pages.settings.skillRepository.cancel')}
            </Button>
            <Button onClick={handleImportSubmit} disabled={importMutation.isPending}>
              {importMutation.isPending
                ? t('pages.settings.skillRepository.importing')
                : t('pages.settings.skillRepository.importAction')}
            </Button>
          </div>
        </div>
      )}

      {showDirtyConfirm && pendingRegistryId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-6 shadow-lg">
            <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">
              {t('pages.settings.codex.updateTitle', { name: pendingRegistryId.toUpperCase() })}
            </h3>
            <p className="mb-4 text-sm text-[var(--text-secondary)]">
              {t('pages.settings.codex.updateWarning')}
            </p>
            <div className="flex justify-end gap-3">
              <Button variant="secondary" onClick={() => setShowDirtyConfirm(false)}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() => {
                  if (pendingRegistryId) {
                    updateRegistryMutation.mutate({ id: pendingRegistryId, force: true });
                  }
                }}
              >
                {t('pages.settings.codex.forceUpdate')}
              </Button>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          {availableSkills.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.settings.skillRepository.noSkills')}
            </div>
          ) : (
            availableSkills.map((skill) => (
              <button
                key={skill.skill_id}
                onClick={() => {
                  setSelectedSkillId(skill.skill_id);
                  setShowPreview(false);
                }}
                className={`flex w-full items-center justify-between rounded-lg border p-3 text-left transition-colors ${
                  selectedSkillId === skill.skill_id
                    ? 'border-[var(--accent)] bg-[var(--bg-secondary)]'
                    : 'border-[var(--border)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)]'
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-[var(--text-primary)]">{skill.label}</p>
                  <p className="text-xs text-[var(--text-tertiary)]">{skill.skill_id}</p>
                </div>
              </button>
            ))
          )}
        </div>

        <div className="space-y-4">
          {!selectedSkillId ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.settings.skillRepository.selectSkill')}
            </div>
          ) : detailQuery.isLoading ? (
            <p className="text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
          ) : detailQuery.error ? (
            <p className="text-sm text-[#ff3b30]">
              {detailQuery.error instanceof Error ? detailQuery.error.message : String(detailQuery.error)}
            </p>
          ) : detailQuery.data ? (
            <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {detailQuery.data.label}
                </h3>
                <span className={getInjectModeBadgeClasses(detailQuery.data.inject_mode)}>
                  {detailQuery.data.inject_mode}
                </span>
              </div>

              <div className="grid gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.version')}</span>
                  <span className="text-[var(--text-primary)]">{detailQuery.data.version}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.author')}</span>
                  <span className="text-[var(--text-primary)]">{detailQuery.data.author}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.dependencies')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.dependencies.length > 0
                      ? detailQuery.data.dependencies.join(', ')
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.mcpServers')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.mcp_servers.length > 0
                      ? detailQuery.data.mcp_servers.join(', ')
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.hooks')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.hooks.length > 0 ? detailQuery.data.hooks.join(', ') : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.allowedAgents')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.allowed_agents.length > 0
                      ? detailQuery.data.allowed_agents.join(', ')
                      : '—'}
                  </span>
                </div>
              </div>

              {detailQuery.data.skill_md ? (
                <div className="space-y-2">
                  <h4 className="text-xs font-medium text-[var(--text-secondary)]">
                    {t('pages.settings.skillRepository.skillMdTitle')}
                  </h4>
                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-xs text-[var(--text-primary)]">
                    {detailQuery.data.skill_md}
                  </pre>
                </div>
              ) : null}

              <Button
                variant="secondary"
                onClick={() => setShowPreview((current) => !current)}
                disabled={previewQuery.isLoading}
              >
                {showPreview
                  ? t('common.cancel')
                  : t('pages.settings.skillRepository.previewSettings')}
              </Button>

              {showPreview && previewQuery.data ? (
                <div className="space-y-2">
                  <h4 className="text-xs font-medium text-[var(--text-secondary)]">
                    {t('pages.settings.skillRepository.settingsPreviewTitle')}
                  </h4>
                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-xs text-[var(--text-primary)]">
                    {JSON.stringify(previewQuery.data.merged_preview, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}

function AccountSection({ onPasswordClick }: { onPasswordClick: () => void }) {
  const t = useT();
  const { user } = useAuth();

  return (
    <SectionCard
      header={
        <SectionHeader
          title={t('pages.settings.account.title')}
          description={t('pages.settings.account.description')}
        />
      }
    >
      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[var(--text)]">{user?.display_name ?? user?.username}</p>
            <p className="text-xs text-[var(--text-secondary)]">{user?.username} · {user?.role}</p>
          </div>
          <Button variant="secondary" onClick={onPasswordClick}>
            {t('auth.changePassword')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}

function VersionSideCard({
  side,
  label,
  commit,
  committedAt,
  commitLabel,
  committedAtLabel,
}: {
  side: 'backend' | 'frontend';
  label: string;
  commit: string;
  committedAt: string;
  commitLabel: string;
  committedAtLabel: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </p>
      <div className="mt-2 space-y-2">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--text-secondary)]">
            {commitLabel}
          </p>
          <p
            className="font-mono text-sm font-medium text-[var(--text)]"
            data-testid={`deployment-version-${side}-commit`}
          >
            {commit}
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--text-secondary)]">
            {committedAtLabel}
          </p>
          <p
            className="font-mono text-sm font-medium text-[var(--text)]"
            data-testid={`deployment-version-${side}-committed-at`}
          >
            {committedAt}
          </p>
        </div>
      </div>
    </div>
  );
}

function DeploymentVersionSection() {
  const t = useT();
  const unavailable = t('pages.settings.version.unavailable');
  const commitLabel = t('pages.settings.version.commitLabel');
  const committedAtLabel = t('pages.settings.version.committedAtLabel');
  const { data: backend } = useQuery({
    queryKey: ['deploymentVersion', 'backend'],
    queryFn: getDeploymentVersion,
  });
  const { data: frontend } = useQuery({
    queryKey: ['deploymentVersion', 'frontend'],
    queryFn: getFrontendBuildVersion,
  });
  const backendCommit = backend?.short_commit ?? unavailable;
  const backendCommittedAt = backend?.committed_at ?? unavailable;
  const frontendCommit = frontend?.short_commit ?? unavailable;
  const frontendCommittedAt = frontend?.committed_at ?? unavailable;
  const mismatched =
    !!backend?.short_commit &&
    !!frontend?.short_commit &&
    backend.short_commit !== frontend.short_commit;

  return (
    <SectionCard
      header={
        <SectionHeader
          title={t('pages.settings.version.title')}
          description={t('pages.settings.version.description')}
        />
      }
    >
      <div className="space-y-3">
        {mismatched && (
          <p
            className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-2 text-sm text-amber-600 dark:text-amber-400"
            data-testid="deployment-version-mismatch"
            role="alert"
          >
            {t('pages.settings.version.mismatchWarning')}
          </p>
        )}
        <div className="grid gap-3 rounded-lg bg-[var(--bg-secondary)] p-4 sm:grid-cols-2">
          <VersionSideCard
            side="backend"
            label={t('pages.settings.version.backendLabel')}
            commit={backendCommit}
            committedAt={backendCommittedAt}
            commitLabel={commitLabel}
            committedAtLabel={committedAtLabel}
          />
          <VersionSideCard
            side="frontend"
            label={t('pages.settings.version.frontendLabel')}
            commit={frontendCommit}
            committedAt={frontendCommittedAt}
            commitLabel={commitLabel}
            committedAtLabel={committedAtLabel}
          />
        </div>
      </div>
    </SectionCard>
  );
}

function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const { logout } = useAuth();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleClose = useCallback(() => {
    setOldPassword('');
    setNewPassword('');
    setConfirm('');
    setError('');
    onClose();
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (newPassword !== confirm) {
      setError(t('auth.passwordMismatch'));
      return;
    }
    if (newPassword.length < 4) {
      setError(t('auth.passwordTooShort'));
      return;
    }
    setSubmitting(true);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      await logout();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t('auth.changePasswordFailed'));
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={handleClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="bg-[var(--surface)] p-6 rounded-2xl border border-[var(--border)] shadow-lg w-full max-w-sm"
      >
        <h2 className="text-lg font-semibold mb-4">{t('auth.changePassword')}</h2>
        {error && <p className="mb-3 text-sm text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.currentPassword')}</span>
            <Input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoFocus
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.newPassword')}</span>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</span>
            <Input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </label>
          <div className="flex gap-2 justify-end mt-2">
            <Button type="button" variant="secondary" onClick={handleClose}>{t('common.cancel')}</Button>
            <Button type="submit" disabled={submitting || !oldPassword || !newPassword || !confirm}>
              {submitting ? t('common.loading') : t('auth.changePassword')}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}

function SettingsPage() {
  const t = useT();
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState<'general' | 'llmProviders' | 'monitoring' | 'users' | 'envAccess' | 'collaborators'>('general');
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: getWorkspaces,
  });
  const skillsQuery = useQuery({
    queryKey: ['skills'],
    queryFn: getSkills,
  });
  const {
    settings,
    recoveryReason,
    saveGeneralPreferences,
    resetGeneralPreferences,
    saveTaskConfigurationSettings,
    resetTaskConfigurationSettings,
    saveProjectDefaultEnvironment,
    saveProjectDefaultWorkspace,
    saveProjectEnvironmentDefaults,
    resetProjectEnvironmentDefaults,
    getProjectEnvironmentDefaults,
    saveAppearanceSettings,
    resetAppearanceSettings,
  } = useSettings();
  const environmentSelection = useEnvironmentSelection();

  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const workspaces = useMemo(
    () => workspacesQuery.data?.items ?? [],
    [workspacesQuery.data]
  );
  const availableSkills = useMemo(
    () => skillsQuery.data?.items ?? [],
    [skillsQuery.data]
  );
  const environmentsError =
    environmentsQuery.error instanceof Error ? environmentsQuery.error.message : null;

  const tabs = [
    { key: 'general' as const, label: t('pages.settings.tabs.general') },
    { key: 'llmProviders' as const, label: t('pages.settings.tabs.llmProviders') },
    { key: 'monitoring' as const, label: t('pages.settings.tabs.monitoring') },
    ...(currentUser?.role === 'admin' ? [
      { key: 'users' as const, label: t('pages.settings.tabs.users') },
      { key: 'envAccess' as const, label: t('pages.settings.tabs.envAccess') },
      { key: 'collaborators' as const, label: t('pages.settings.tabs.collaborators') },
    ] : []),
  ];

  return (
    <PageShell>
      <div className="space-y-8 p-4">
        <PageHeader
          eyebrow={t('pages.settings.eyebrow')}
          title={t('pages.settings.title')}
          description={t('pages.settings.description')}
        />

        <div className="flex gap-1 border-b border-[var(--border)] pb-0">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg border border-b-0 -mb-px transition-colors ${
                activeTab === tab.key
                  ? 'bg-[var(--surface)] border-[var(--border)] text-[var(--text)]'
                  : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--bg-secondary)]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'general' && (
          <SectionStack>
          {recoveryReason !== null ? <Alert variant="warning">{t('pages.settings.recoveryNotice')}</Alert> : null}

          <GeneralPreferencesSection
            key={`general:${settings.general.defaultRoute}:${settings.general.terminal.fontSize}`}
            savedGeneral={settings.general}
            onSave={saveGeneralPreferences}
            onReset={resetGeneralPreferences}
          />

          <AppearanceSection
            savedAppearance={settings.general.appearance}
            onSave={saveAppearanceSettings}
            onReset={resetAppearanceSettings}
          />

          <EnvironmentSelectorPanel {...environmentSelection} />

          <SectionCard
            collapsible
            header={
              <SectionHeader
                title={t('pages.settings.defaultWorkspace.title')}
                description={t('pages.settings.defaultWorkspace.description')}
              />
            }
          >
            <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
              <FormField label={t('pages.settings.defaultWorkspace.label')}>
                <Select
                  aria-label={t('pages.settings.defaultWorkspace.label')}
                  value={settings.projectDefaults.default?.defaultWorkspaceId ?? ''}
                  onChange={(event) =>
                    saveProjectDefaultWorkspace('default', event.target.value || null)
                  }
                  disabled={workspaces.length === 0}
                >
                  <option value="">{t('pages.settings.defaultWorkspace.noDefault')}</option>
                  {workspaces.map((workspace) => (
                    <option key={workspace.workspace_id} value={workspace.workspace_id}>
                      {workspace.label}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </SectionCard>

          <TaskConfigurationSection
            taskConfiguration={settings.taskConfiguration}
            availableSkills={availableSkills}
            onSaveTaskConfigurationSettings={saveTaskConfigurationSettings}
            onResetTaskConfigurationSettings={resetTaskConfigurationSettings}
          />

          <SkillRepositorySection availableSkills={availableSkills} />
          <AccountSection onPasswordClick={() => setShowPasswordModal(true)} />
          <DeploymentVersionSection />
          <ChangePasswordModal open={showPasswordModal} onClose={() => setShowPasswordModal(false)} />
          <SearchBackendSection />

          <ProjectDefaultsSection
            key={`project-default:${settings.projectDefaults.default?.defaultEnvironmentId ?? 'none'}`}
            environments={environments}
            taskConfiguration={settings.taskConfiguration}
            savedDefaultEnvironmentId={settings.projectDefaults.default?.defaultEnvironmentId ?? null}
            isLoading={environmentsQuery.isLoading}
            loadError={environmentsError}
            getProjectEnvironmentDefaults={(environmentId) =>
              getProjectEnvironmentDefaults('default', environmentId)
            }
            saveProjectDefaultEnvironment={(environmentId) =>
              saveProjectDefaultEnvironment('default', environmentId)
            }
            saveProjectEnvironmentDefaults={(environmentId, defaults) =>
              saveProjectEnvironmentDefaults('default', environmentId, defaults)
            }
            resetProjectEnvironmentDefaults={(environmentId) =>
              resetProjectEnvironmentDefaults('default', environmentId)
            }
          />
        </SectionStack>
        )}

        {activeTab === 'llmProviders' && <LlmProvidersTab />}
        {activeTab === 'monitoring' && <MonitoringTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'envAccess' && <EnvAccessTab />}
        {activeTab === 'collaborators' && <CollaboratorsTab />}
      </div>
    </PageShell>
  );
}

export default SettingsPage;
