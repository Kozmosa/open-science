import { useMemo, useState } from 'react';
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
  Textarea,
} from '../components/ui';
import { EnvironmentSelectorPanel, useEnvironmentSelection } from '../components';
import TerminalSessionConsole from '../components/terminal/TerminalSessionConsole';
import { getEnvironments, installEnvironmentCodeServer } from '../api';
import { useT } from '../i18n';
import {
  clampTerminalFontSize,
  maxTerminalFontSize,
  minTerminalFontSize,
  useSettings,
} from '../settings';
import type {
  DefaultRoute,
  EnvironmentTaskDefaults,
  ResearchAgentProfileSettings,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from '../settings';
import type { EnvironmentRecord } from '../types';

interface CodeServerInstallTerminalState {
  sessionId: string | null;
  attachmentId: string | null;
  terminalWsUrl: string | null;
}

interface GeneralDraftState {
  defaultRoute: DefaultRoute;
  terminalFontSize: string;
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

interface CodeServerInstallSectionProps {
  environment: EnvironmentRecord | null;
  isPending: boolean;
  error: string | null;
  successDetail: string | null;
  terminalState: CodeServerInstallTerminalState | null;
  onInstall: (environmentId: string) => void;
}

interface TaskConfigurationSectionProps {
  taskConfiguration: TaskConfigurationSettings;
  onSaveResearchAgentProfile: (profile: ResearchAgentProfileSettings) => void;
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
  });
  const clampedFontSize = clampTerminalFontSize(Number.parseInt(draft.terminalFontSize, 10));
  const hasChanges =
    draft.defaultRoute !== savedGeneral.defaultRoute ||
    clampedFontSize !== savedGeneral.terminal.fontSize;

  return (
    <SectionCard>
      <SectionHeader
        title={t('pages.settings.general.title')}
        description={t('pages.settings.general.description')}
      />

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
            <option value="containers">{t('pages.settings.routes.containers')}</option>
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
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>
          {t('pages.settings.general.terminalFontSizeHelp', {
            min: minTerminalFontSize,
            max: maxTerminalFontSize,
            current: clampedFontSize,
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
                  fontSize: clampedFontSize,
                },
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

function CodeServerInstallSection({
  environment,
  isPending,
  error,
  successDetail,
  terminalState,
  onInstall,
}: CodeServerInstallSectionProps) {
  const t = useT();
  const installedPath = environment?.code_server_path ?? null;

  return (
    <SectionCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeader
          title={t('pages.settings.codeServerInstall.title')}
          description={t('pages.settings.codeServerInstall.description')}
        />
        <Button
          onClick={() => (environment ? onInstall(environment.id) : undefined)}
          disabled={!environment || isPending}
        >
          {isPending
            ? t('pages.settings.codeServerInstall.installing')
            : t('pages.settings.codeServerInstall.installAction')}
        </Button>
      </div>

      <div className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px]">
        <p className="text-[var(--text-secondary)]">
          <span className="font-medium text-[var(--text)]">
            {t('pages.settings.codeServerInstall.selectedEnvironment')}
          </span>{' '}
          {environment ? `${environment.alias} · ${environment.display_name}` : t('common.notSelected')}
        </p>
        <p className="break-all text-[var(--text-secondary)]">
          <span className="font-medium text-[var(--text)]">
            {t('pages.settings.codeServerInstall.installedPath')}
          </span>{' '}
          {installedPath ?? t('pages.settings.codeServerInstall.notInstalled')}
        </p>
        {successDetail ? <p className="text-[#34c759]">{successDetail}</p> : null}
        {error ? <p className="text-[#ff3b30]">{error}</p> : null}
      </div>

      {terminalState?.attachmentId && terminalState.terminalWsUrl ? (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h3 className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.codeServerInstall.terminalOutput')}
          </h3>
          <div className="min-h-[260px] overflow-hidden rounded-lg border border-[var(--border)] bg-black">
            <TerminalSessionConsole
              sessionId={terminalState.sessionId ?? environment?.id ?? null}
              attachmentId={terminalState.attachmentId}
              terminalWsUrl={terminalState.terminalWsUrl}
              status="running"
              readonly
              placeholderText={t('pages.settings.codeServerInstall.terminalPlaceholder')}
            />
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

function TaskConfigurationSection({
  taskConfiguration,
  onSaveResearchAgentProfile,
  onSaveTaskConfigurationSettings,
  onResetTaskConfigurationSettings,
}: TaskConfigurationSectionProps) {
  const t = useT();
  const [profileDraft, setProfileDraft] = useState<ResearchAgentProfileSettings>(
    taskConfiguration.researchAgentProfiles[0] ?? {
      profileId: 'claude-code-default',
      label: 'Claude Code Default',
      systemPrompt: '',
      skillsPrompt: '',
      settingsJson: '',
    }
  );
  const [defaultProfileId, setDefaultProfileId] = useState(
    taskConfiguration.defaultResearchAgentProfileId
  );
  const [defaultConfigId, setDefaultConfigId] = useState(taskConfiguration.defaultTaskConfigurationId);

  return (
    <SectionCard>
      <SectionHeader
        title={t('pages.settings.taskConfiguration.title')}
        description={t('pages.settings.taskConfiguration.description')}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.taskConfiguration.executionEngineLabel')}>
          <Select
            aria-label={t('pages.settings.taskConfiguration.executionEngineLabel')}
            value={taskConfiguration.defaultExecutionEngineId}
            disabled
          >
            <option value="claude-code">Claude Code</option>
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

        <FormField label={t('pages.settings.taskConfiguration.skillsPromptLabel')}>
          <Textarea
            aria-label={t('pages.settings.taskConfiguration.skillsPromptLabel')}
            value={profileDraft.skillsPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, skillsPrompt: event.target.value }))
            }
            className="min-h-24"
          />
        </FormField>

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
            onSaveResearchAgentProfile(profileDraft);
            onSaveTaskConfigurationSettings({
              ...taskConfiguration,
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
    <SectionCard className="space-y-4 p-5">
      <SectionHeader
        title={`${environment.alias} · ${environment.display_name}`}
        description={t('pages.settings.project.environmentCardDescription')}
        size="sm"
      />

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
    <SectionCard>
      <SectionHeader
        title={t('pages.settings.project.title')}
        description={t('pages.settings.project.description')}
      />

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

function SettingsPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const [installSuccessDetail, setInstallSuccessDetail] = useState<string | null>(null);
  const [installTerminalState, setInstallTerminalState] =
    useState<CodeServerInstallTerminalState | null>(null);
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const {
    settings,
    recoveryReason,
    saveGeneralPreferences,
    resetGeneralPreferences,
    saveTaskConfigurationSettings,
    resetTaskConfigurationSettings,
    saveResearchAgentProfile,
    saveProjectDefaultEnvironment,
    saveProjectEnvironmentDefaults,
    resetProjectEnvironmentDefaults,
    getProjectEnvironmentDefaults,
  } = useSettings();
  const environmentSelection = useEnvironmentSelection();

  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const selectedEnvironment =
    environmentSelection.selectedEnvironmentId !== null
      ? (environments.find(
          (environment) => environment.id === environmentSelection.selectedEnvironmentId
        ) ?? environmentSelection.selectedEnvironment)
      : (environmentSelection.selectedEnvironment ?? environments[0] ?? null);
  const installMutation = useMutation({
    mutationFn: installEnvironmentCodeServer,
    onMutate: (environmentId) => {
      const environment = environments.find((item) => item.id === environmentId) ?? null;
      console.info('code-server install requested', {
        environmentId,
        alias: environment?.alias ?? null,
      });
      setInstallTerminalState(null);
    },
    onSuccess: async (response) => {
      console.info('code-server install succeeded', {
        environmentId: response.environment.id,
        alias: response.environment.alias,
        executionMode: response.execution_mode,
        alreadyInstalled: response.already_installed,
        codeServerPath: response.code_server_path,
      });
      setInstallSuccessDetail(response.detail);
      setInstallTerminalState(
        response.terminal_attachment_id && response.terminal_ws_url
          ? {
              sessionId: response.terminal_session_id ?? null,
              attachmentId: response.terminal_attachment_id,
              terminalWsUrl: response.terminal_ws_url,
            }
          : null
      );
      queryClient.setQueryData(['environments'], { items: [response.environment] });
      await queryClient.invalidateQueries({ queryKey: ['environments'] });
    },
    onError: (error, environmentId) => {
      const environment = environments.find((item) => item.id === environmentId) ?? null;
      console.error('code-server install failed', {
        environmentId,
        alias: environment?.alias ?? null,
        error: error instanceof Error ? error.message : error,
      });
      setInstallSuccessDetail(null);
      setInstallTerminalState(null);
    },
  });
  const installError =
    installMutation.error instanceof Error ? installMutation.error.message : null;
  const environmentsError =
    environmentsQuery.error instanceof Error ? environmentsQuery.error.message : null;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={t('pages.settings.eyebrow')}
        title={t('pages.settings.title')}
        description={t('pages.settings.description')}
      />

      <div className="space-y-6">
        {recoveryReason !== null ? (
          <Alert variant="warning">{t('pages.settings.recoveryNotice')}</Alert>
        ) : null}

        <GeneralPreferencesSection
          key={`general:${settings.general.defaultRoute}:${settings.general.terminal.fontSize}`}
          savedGeneral={settings.general}
          onSave={saveGeneralPreferences}
          onReset={resetGeneralPreferences}
        />

        <EnvironmentSelectorPanel {...environmentSelection} />

        <CodeServerInstallSection
          environment={selectedEnvironment}
          isPending={installMutation.isPending}
          error={installError}
          successDetail={installSuccessDetail}
          terminalState={installTerminalState}
          onInstall={(environmentId) => installMutation.mutate(environmentId)}
        />

        <TaskConfigurationSection
          taskConfiguration={settings.taskConfiguration}
          onSaveResearchAgentProfile={saveResearchAgentProfile}
          onSaveTaskConfigurationSettings={saveTaskConfigurationSettings}
          onResetTaskConfigurationSettings={resetTaskConfigurationSettings}
        />

        <ProjectDefaultsSection
          key={`project-default:${settings.projectDefaults.default.defaultEnvironmentId ?? 'none'}`}
          environments={environments}
          taskConfiguration={settings.taskConfiguration}
          savedDefaultEnvironmentId={settings.projectDefaults.default.defaultEnvironmentId}
          isLoading={environmentsQuery.isLoading}
          loadError={environmentsError}
          getProjectEnvironmentDefaults={getProjectEnvironmentDefaults}
          saveProjectDefaultEnvironment={saveProjectDefaultEnvironment}
          saveProjectEnvironmentDefaults={saveProjectEnvironmentDefaults}
          resetProjectEnvironmentDefaults={resetProjectEnvironmentDefaults}
        />
      </div>
    </div>
  );
}

export default SettingsPage;
