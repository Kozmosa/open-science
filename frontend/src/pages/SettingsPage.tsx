import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-1">
        <h2
          className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.settings.general.title')}
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('pages.settings.general.description')}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.general.defaultRouteLabel')}
          </span>
          <select
            aria-label={t('pages.settings.general.defaultRouteLabel')}
            value={draft.defaultRoute}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                defaultRoute: event.target.value as DefaultRoute,
              }))
            }
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          >
            <option value="terminal">{t('pages.settings.routes.terminal')}</option>
            <option value="tasks">{t('pages.settings.routes.tasks')}</option>
            <option value="workspaces">{t('pages.settings.routes.workspaces')}</option>
            <option value="containers">{t('pages.settings.routes.containers')}</option>
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.general.terminalFontSizeLabel')}
          </span>
          <input
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
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          />
        </label>
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
          <button
            type="button"
            onClick={onReset}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
          >
            {t('common.reset')}
          </button>
          <button
            type="button"
            onClick={() =>
              onSave({
                defaultRoute: draft.defaultRoute,
                terminal: {
                  fontSize: clampedFontSize,
                },
              })
            }
            disabled={!hasChanges}
            className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('common.saveChanges')}
          </button>
        </div>
      </div>
    </section>
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
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2
            className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {t('pages.settings.codeServerInstall.title')}
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.settings.codeServerInstall.description')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => (environment ? onInstall(environment.id) : undefined)}
          disabled={!environment || isPending}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isPending
            ? t('pages.settings.codeServerInstall.installing')
            : t('pages.settings.codeServerInstall.installAction')}
        </button>
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
    </section>
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
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-1">
        <h2
          className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.settings.taskConfiguration.title')}
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('pages.settings.taskConfiguration.description')}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.executionEngineLabel')}
          </span>
          <select
            aria-label={t('pages.settings.taskConfiguration.executionEngineLabel')}
            value={taskConfiguration.defaultExecutionEngineId}
            disabled
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)]"
          >
            <option value="claude-code">Claude Code</option>
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}
          </span>
          <select
            aria-label={t('pages.settings.taskConfiguration.defaultTaskConfigurationLabel')}
            value={defaultConfigId}
            onChange={(event) => setDefaultConfigId(event.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          >
            {taskConfiguration.taskConfigurations.map((config) => (
              <option key={config.configId} value={config.configId}>
                {config.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.defaultResearchAgentLabel')}
          </span>
          <select
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
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          >
            {taskConfiguration.researchAgentProfiles.map((profile) => (
              <option key={profile.profileId} value={profile.profileId}>
                {profile.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.profileLabel')}
          </span>
          <input
            aria-label={t('pages.settings.taskConfiguration.profileLabel')}
            value={profileDraft.label}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, label: event.target.value }))
            }
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          />
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.systemPromptLabel')}
          </span>
          <textarea
            aria-label={t('pages.settings.taskConfiguration.systemPromptLabel')}
            value={profileDraft.systemPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, systemPrompt: event.target.value }))
            }
            className="min-h-24 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          />
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.skillsPromptLabel')}
          </span>
          <textarea
            aria-label={t('pages.settings.taskConfiguration.skillsPromptLabel')}
            value={profileDraft.skillsPrompt}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, skillsPrompt: event.target.value }))
            }
            className="min-h-24 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          />
        </label>

        <label className="block space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.taskConfiguration.settingsJsonLabel')}
          </span>
          <textarea
            aria-label={t('pages.settings.taskConfiguration.settingsJsonLabel')}
            value={profileDraft.settingsJson}
            onChange={(event) =>
              setProfileDraft((current) => ({ ...current, settingsJson: event.target.value }))
            }
            className="min-h-28 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 font-mono text-xs tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          />
        </label>
      </div>

      <div className="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          onClick={onResetTaskConfigurationSettings}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
        >
          {t('common.reset')}
        </button>
        <button
          type="button"
          onClick={() => {
            onSaveResearchAgentProfile(profileDraft);
            onSaveTaskConfigurationSettings({
              ...taskConfiguration,
              defaultResearchAgentProfileId: defaultProfileId,
              defaultTaskConfigurationId: defaultConfigId,
            });
          }}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)]"
        >
          {t('common.saveChanges')}
        </button>
      </div>
    </section>
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
    <section className="space-y-4 rounded-xl bg-[var(--surface)] p-5 shadow-sm">
      <div className="space-y-1">
        <h3
          className="text-base font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {environment.alias} · {environment.display_name}
        </h3>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('pages.settings.project.environmentCardDescription')}
        </p>
      </div>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.settings.project.titleTemplateLabel')}
        </span>
        <input
          aria-label={`${environment.alias} ${t('pages.settings.project.titleTemplateLabel')}`}
          value={draft.titleTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              titleTemplate: event.target.value,
            }))
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder={t('pages.settings.project.titleTemplatePlaceholder')}
        />
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.settings.project.taskInputTemplateLabel')}
        </span>
        <textarea
          aria-label={`${environment.alias} ${t('pages.settings.project.taskInputTemplateLabel')}`}
          value={draft.taskInputTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskInputTemplate: event.target.value,
            }))
          }
          className="min-h-32 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder={t('pages.settings.project.taskInputTemplatePlaceholder')}
        />
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.settings.project.researchAgentDefaultLabel')}
        </span>
        <select
          aria-label={`${environment.alias} ${t('pages.settings.project.researchAgentDefaultLabel')}`}
          value={draft.researchAgentProfileId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              researchAgentProfileId: event.target.value,
            }))
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {taskConfiguration.researchAgentProfiles.map((profile) => (
            <option key={profile.profileId} value={profile.profileId}>
              {profile.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.settings.project.taskConfigurationDefaultLabel')}
        </span>
        <select
          aria-label={`${environment.alias} ${t('pages.settings.project.taskConfigurationDefaultLabel')}`}
          value={draft.taskConfigurationId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskConfigurationId: event.target.value,
            }))
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {taskConfiguration.taskConfigurations.map((config) => (
            <option key={config.configId} value={config.configId}>
              {config.label}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          onClick={onReset}
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
        >
          {t('common.reset')}
        </button>
        <button
          type="button"
          onClick={() => onSave(draft)}
          disabled={!hasChanges}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t('common.saveChanges')}
        </button>
      </div>
    </section>
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
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-1">
        <h2
          className="text-lg font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.settings.project.title')}
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('pages.settings.project.description')}
        </p>
      </div>

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.settings.project.defaultEnvironmentLabel')}
          </span>
          <select
            aria-label={t('pages.settings.project.defaultEnvironmentLabel')}
            value={defaultEnvironmentDraft}
            onChange={(event) => setDefaultEnvironmentDraft(event.target.value)}
            disabled={environments.length === 0}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15 disabled:cursor-not-allowed disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-tertiary)]"
          >
            <option value="">{t('pages.settings.project.defaultEnvironmentEmpty')}</option>
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.settings.project.defaultEnvironmentHelp')}
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => saveProjectDefaultEnvironment(null)}
              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
            >
              {t('common.reset')}
            </button>
            <button
              type="button"
              onClick={() => saveProjectDefaultEnvironment(defaultEnvironmentDraft || null)}
              disabled={!hasProjectDefaultChanges}
              className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t('common.saveChanges')}
            </button>
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
    </section>
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
    onMutate: () => {
      setInstallTerminalState(null);
    },
    onSuccess: async (response) => {
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
    onError: () => {
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
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.settings.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.settings.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.settings.description')}
        </p>
      </section>

      <div className="space-y-6">
        {recoveryReason !== null ? (
          <section className="rounded-lg border border-[#ffb74d]/30 bg-[#fff8e1] px-4 py-3 text-sm tracking-[-0.224px] text-[#e65100]">
            {t('pages.settings.recoveryNotice')}
          </section>
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
