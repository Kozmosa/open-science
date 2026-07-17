/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from 'react';
import { applyOsciTheme } from '@design-system';
import {
  clampEditorFontSize,
  clampTerminalFontSize,
  createDefaultTaskConfigurationSettings,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  isDefaultRoute,
} from '@features/settings/utils/defaults';
import { readStoredSettings, resolveProjectEnvironmentDefaults, writeStoredSettings, normalizeLlmProviders } from '@features/settings/utils/storage';
import type {
  DefaultProjectSettings,
  EnvironmentTaskDefaults,
  SettingsRecoveryReason,
  WebUiSettingsDocument,
} from '@features/settings/types';

import { GeneralSettingsProvider } from './GeneralSettingsContext';
import { AppearanceSettingsProvider } from './AppearanceSettingsContext';
import { TaskConfigurationProvider } from './TaskConfigurationContext';
import { ProjectDefaultsProvider } from './ProjectDefaultsContext';
import { LlmProvidersProvider } from './LlmProvidersContext';

// ── Shared state helpers ──────────────────────────────────────────

interface SettingsState {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
}

function getOrCreateProjectSettings(
  projectDefaults: Record<string, DefaultProjectSettings>,
  projectId: string
): DefaultProjectSettings {
  return (
    projectDefaults[projectId] ?? {
      defaultEnvironmentId: null,
      defaultWorkspaceId: null,
      selection: { lastEnvironmentId: null, lastWorkspaceId: null },
      environmentDefaults: {},
    }
  );
}

function sanitizeSettings(settings: WebUiSettingsDocument): WebUiSettingsDocument {
  const editorFontSize = clampEditorFontSize(settings.general.editor?.fontSize);
  const editorFontFamily =
    typeof settings.general.editor?.fontFamily === 'string' &&
    settings.general.editor.fontFamily.length > 0
      ? settings.general.editor.fontFamily
      : 'monospace';

  const appearanceTheme =
    settings.general.appearance?.theme === 'dark' || settings.general.appearance?.theme === 'system'
      ? settings.general.appearance.theme
      : 'light';

  const sanitizedProjectDefaults: Record<string, DefaultProjectSettings> = {};
  for (const [projectId, projectSettings] of Object.entries(settings.projectDefaults)) {
    sanitizedProjectDefaults[projectId] = {
      defaultEnvironmentId:
        typeof projectSettings.defaultEnvironmentId === 'string'
          ? projectSettings.defaultEnvironmentId : null,
      defaultWorkspaceId:
        typeof projectSettings.defaultWorkspaceId === 'string'
          ? projectSettings.defaultWorkspaceId : null,
      selection: {
        lastEnvironmentId:
          typeof projectSettings.selection?.lastEnvironmentId === 'string'
            ? projectSettings.selection.lastEnvironmentId : null,
        lastWorkspaceId:
          typeof projectSettings.selection?.lastWorkspaceId === 'string'
            ? projectSettings.selection.lastWorkspaceId : null,
      },
      environmentDefaults:
        typeof projectSettings.environmentDefaults === 'object' &&
        projectSettings.environmentDefaults !== null
          ? projectSettings.environmentDefaults : {},
    };
  }

  if (!sanitizedProjectDefaults.default) {
    sanitizedProjectDefaults.default = {
      defaultEnvironmentId: null,
      defaultWorkspaceId: null,
      selection: { lastEnvironmentId: null, lastWorkspaceId: null },
      environmentDefaults: {},
    };
  }

  return {
    version: 5,
    general: {
      defaultRoute: isDefaultRoute(settings.general.defaultRoute)
        ? settings.general.defaultRoute : 'today',
      terminal: { fontSize: clampTerminalFontSize(settings.general.terminal.fontSize) },
      editor: { fontSize: editorFontSize, fontFamily: editorFontFamily },
      appearance: { theme: appearanceTheme },
    },
    taskConfiguration: settings.taskConfiguration,
    projectDefaults: sanitizedProjectDefaults,
    llmProviders: normalizeLlmProviders(settings.llmProviders),
  };
}

// ── Legacy context (backwards compatible) ─────────────────────────

const LegacySettingsContext = createContext<{
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  activeProjectId: string;
  setActiveProjectId: (projectId: string) => void;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  resetAppearanceSettings: () => void;
  saveTaskConfigurationSettings: (tc: WebUiSettingsDocument['taskConfiguration']) => void;
  resetTaskConfigurationSettings: () => void;
  saveResearchAgentProfile: (p: WebUiSettingsDocument['taskConfiguration']['researchAgentProfiles'][number]) => void;
  saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => void;
  saveProjectDefaultWorkspace: (projectId: string, workspaceId: string | null) => void;
  saveProjectEnvironmentDefaults: (projectId: string, environmentId: string, defaults: EnvironmentTaskDefaults) => void;
  resetProjectEnvironmentDefaults: (projectId: string, environmentId: string) => void;
  rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => void;
  rememberSelectedWorkspace: (projectId: string, workspaceId: string | null) => void;
  getProjectEnvironmentDefaults: (projectId: string, environmentId: string | null) => EnvironmentTaskDefaults;
  saveLlmProvider: (provider: WebUiSettingsDocument['llmProviders'][number]) => void;
  updateLlmProvider: (provider: WebUiSettingsDocument['llmProviders'][number]) => void;
  deleteLlmProvider: (providerId: string) => void;
} | null>(null);

// ── Composite Provider ───────────────────────────────────────────

interface ProviderProps {
  children: ReactNode;
  userId?: string;
}

export function SettingsProvider({ children, userId = 'test-user' }: ProviderProps) {
  const [state, setState] = useState<SettingsState>(() => readStoredSettings(userId));
  const [activeProjectId, setActiveProjectId] = useState<string>('default');

  useLayoutEffect(() => {
    const preference = state.settings.general.appearance.theme;
    applyOsciTheme(preference);
    if (preference !== 'system' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => applyOsciTheme('system');
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [state.settings.general.appearance.theme]);

  const commitSettings = useCallback((nextSettings: WebUiSettingsDocument): void => {
    const sanitized = sanitizeSettings(nextSettings);
    writeStoredSettings(sanitized, userId);
    setState({ settings: sanitized, recoveryReason: null });
  }, [userId]);

  // ── Domain context values ────────────────────────────────────

  const generalValue = useMemo(() => ({
    settings: state.settings,
    recoveryReason: state.recoveryReason,
    saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => {
      commitSettings({
        ...state.settings,
        general: {
          defaultRoute: general.defaultRoute,
          terminal: { fontSize: general.terminal.fontSize },
          editor: { fontSize: general.editor.fontSize, fontFamily: general.editor.fontFamily },
          appearance: state.settings.general.appearance,
        },
      });
    },
    resetGeneralPreferences: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: defaults.general });
    },
    saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => {
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance } });
    },
    resetAppearanceSettings: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance: defaults.general.appearance } });
    },
  }), [state, commitSettings]);

  const appearanceValue = useMemo(() => ({
    appearance: state.settings.general.appearance,
    saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => {
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance } });
    },
    resetAppearanceSettings: () => {
      const defaults = createDefaultWebUiSettings();
      commitSettings({ ...state.settings, general: { ...state.settings.general, appearance: defaults.general.appearance } });
    },
  }), [state, commitSettings]);

  const taskConfigurationValue = useMemo(() => ({
    taskConfiguration: state.settings.taskConfiguration,
    saveTaskConfigurationSettings: (tc: WebUiSettingsDocument['taskConfiguration']) => {
      commitSettings({ ...state.settings, taskConfiguration: tc });
    },
    resetTaskConfigurationSettings: () => {
      commitSettings({ ...state.settings, taskConfiguration: createDefaultTaskConfigurationSettings() });
    },
    saveResearchAgentProfile: (profile: WebUiSettingsDocument['taskConfiguration']['researchAgentProfiles'][number]) => {
      const profiles = state.settings.taskConfiguration.researchAgentProfiles;
      const exists = profiles.some((p) => p.profileId === profile.profileId);
      commitSettings({
        ...state.settings,
        taskConfiguration: {
          ...state.settings.taskConfiguration,
          researchAgentProfiles: exists
            ? profiles.map((p) => (p.profileId === profile.profileId ? profile : p))
            : [...profiles, profile],
        },
      });
    },
  }), [state, commitSettings]);

  const projectDefaultsValue = useMemo(() => ({
    activeProjectId,
    setActiveProjectId,
    saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: { ...state.settings.projectDefaults, [projectId]: { ...cp, defaultEnvironmentId: environmentId } },
      });
    },
    saveProjectDefaultWorkspace: (projectId: string, workspaceId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: { ...state.settings.projectDefaults, [projectId]: { ...cp, defaultWorkspaceId: workspaceId } },
      });
    },
    saveProjectEnvironmentDefaults: (projectId: string, environmentId: string, defaults: EnvironmentTaskDefaults) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: {
          ...state.settings.projectDefaults,
          [projectId]: {
            ...cp,
            environmentDefaults: { ...cp.environmentDefaults, [environmentId]: {
              titleTemplate: defaults.titleTemplate,
              taskInputTemplate: defaults.taskInputTemplate,
              researchAgentProfileId: defaults.researchAgentProfileId,
              taskConfigurationId: defaults.taskConfigurationId,
            }},
          },
        },
      });
    },
    resetProjectEnvironmentDefaults: (projectId: string, environmentId: string) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      const next = { ...cp.environmentDefaults };
      delete next[environmentId];
      commitSettings({
        ...state.settings,
        projectDefaults: { ...state.settings.projectDefaults, [projectId]: { ...cp, environmentDefaults: next } },
      });
    },
    rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: {
          ...state.settings.projectDefaults,
          [projectId]: { ...cp, selection: { ...cp.selection, lastEnvironmentId: environmentId } },
        },
      });
    },
    rememberSelectedWorkspace: (projectId: string, workspaceId: string | null) => {
      const cp = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
      commitSettings({
        ...state.settings,
        projectDefaults: {
          ...state.settings.projectDefaults,
          [projectId]: { ...cp, selection: { ...cp.selection, lastWorkspaceId: workspaceId } },
        },
      });
    },
    getProjectEnvironmentDefaults: (projectId: string, environmentId: string | null) =>
      resolveProjectEnvironmentDefaults(state.settings, projectId, environmentId),
  }), [state, activeProjectId, commitSettings]);

  const llmProvidersValue = useMemo(() => ({
    llmProviders: state.settings.llmProviders,
    saveLlmProvider: (provider: WebUiSettingsDocument['llmProviders'][number]) => {
      commitSettings({ ...state.settings, llmProviders: [...state.settings.llmProviders, provider] });
    },
    updateLlmProvider: (provider: WebUiSettingsDocument['llmProviders'][number]) => {
      commitSettings({
        ...state.settings,
        llmProviders: state.settings.llmProviders.map((p) => (p.id === provider.id ? provider : p)),
      });
    },
    deleteLlmProvider: (providerId: string) => {
      commitSettings({
        ...state.settings,
        llmProviders: state.settings.llmProviders.filter((p) => p.id !== providerId),
      });
    },
  }), [state, commitSettings]);

  // ── Legacy value for backwards compatibility ─────────────────

  const legacyValue = useMemo(() => {
    // generalValue carries `settings`/`recoveryReason` as well — avoid duplicate keys
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { settings: _settings, recoveryReason: _recoveryReason, ...generalRest } = generalValue;
    return {
      settings: state.settings,
      recoveryReason: state.recoveryReason,
      ...generalRest,
      ...appearanceValue,
      ...taskConfigurationValue,
      ...projectDefaultsValue,
      ...llmProvidersValue,
    };
  }, [state, generalValue, appearanceValue, taskConfigurationValue, projectDefaultsValue, llmProvidersValue]);

  return (
    <LegacySettingsContext.Provider value={legacyValue}>
      <GeneralSettingsProvider value={generalValue}>
        <AppearanceSettingsProvider value={appearanceValue}>
          <TaskConfigurationProvider value={taskConfigurationValue}>
            <ProjectDefaultsProvider value={projectDefaultsValue}>
              <LlmProvidersProvider value={llmProvidersValue}>
                {children}
              </LlmProvidersProvider>
            </ProjectDefaultsProvider>
          </TaskConfigurationProvider>
        </AppearanceSettingsProvider>
      </GeneralSettingsProvider>
    </LegacySettingsContext.Provider>
  );
}

// ── Legacy hook (deprecated) ─────────────────────────────────────

/** @deprecated Prefer useGeneralSettings / useAppearanceSettings / useTaskConfiguration / useProjectDefaults / useLlmProviders */
export function useSettings() {
  const context = useContext(LegacySettingsContext);
  if (context === null) {
    throw new Error('useSettings must be used within a SettingsProvider');
  }
  return context;
}

export function useTerminalFontSize(): number {
  return useSettings().settings.general.terminal.fontSize;
}

export function useEditorSettings(): { fontSize: number; fontFamily: string } {
  const { settings } = useSettings();
  return { fontSize: settings.general.editor.fontSize, fontFamily: settings.general.editor.fontFamily };
}

export function useProjectEnvironmentDefaults(
  projectId: string,
  environmentId: string | null
): EnvironmentTaskDefaults {
  return useSettings().getProjectEnvironmentDefaults(projectId, environmentId) ?? createEmptyEnvironmentTaskDefaults();
}
