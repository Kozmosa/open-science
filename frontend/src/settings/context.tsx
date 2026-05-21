/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getCodexDefaults } from '../api';
import {
  applyCodexDefaultsToProfile,
  clampEditorFontSize,
  clampTerminalFontSize,
  createCodexAppServerResearchAgentProfile,
  createDefaultTaskConfigurationSettings,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  isDefaultRoute,
} from './defaults';
import { readStoredSettings, resolveProjectEnvironmentDefaults, writeStoredSettings } from './storage';
import type {
  DefaultProjectSettings,
  EnvironmentTaskDefaults,
  ResearchAgentProfileSettings,
  SettingsRecoveryReason,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from './types';

interface SettingsContextValue {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  activeProjectId: string;
  setActiveProjectId: (projectId: string) => void;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveTaskConfigurationSettings: (taskConfiguration: TaskConfigurationSettings) => void;
  resetTaskConfigurationSettings: () => void;
  saveResearchAgentProfile: (profile: ResearchAgentProfileSettings) => void;
  saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => void;
  saveProjectDefaultWorkspace: (projectId: string, workspaceId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    projectId: string,
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (projectId: string, environmentId: string) => void;
  rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => void;
  rememberSelectedWorkspace: (projectId: string, workspaceId: string | null) => void;
  getProjectEnvironmentDefaults: (projectId: string, environmentId: string | null) => EnvironmentTaskDefaults;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

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
      selection: {
        lastEnvironmentId: null,
        lastWorkspaceId: null,
      },
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

  const sanitizedProjectDefaults: Record<string, DefaultProjectSettings> = {};
  for (const [projectId, projectSettings] of Object.entries(settings.projectDefaults)) {
    sanitizedProjectDefaults[projectId] = {
      defaultEnvironmentId:
        typeof projectSettings.defaultEnvironmentId === 'string'
          ? projectSettings.defaultEnvironmentId
          : null,
      defaultWorkspaceId:
        typeof projectSettings.defaultWorkspaceId === 'string'
          ? projectSettings.defaultWorkspaceId
          : null,
      selection: {
        lastEnvironmentId:
          typeof projectSettings.selection?.lastEnvironmentId === 'string'
            ? projectSettings.selection.lastEnvironmentId
            : null,
        lastWorkspaceId:
          typeof projectSettings.selection?.lastWorkspaceId === 'string'
            ? projectSettings.selection.lastWorkspaceId
            : null,
      },
      environmentDefaults:
        typeof projectSettings.environmentDefaults === 'object' &&
        projectSettings.environmentDefaults !== null
          ? projectSettings.environmentDefaults
          : {},
    };
  }

  if (!sanitizedProjectDefaults.default) {
    sanitizedProjectDefaults.default = {
      defaultEnvironmentId: null,
      defaultWorkspaceId: null,
      selection: {
        lastEnvironmentId: null,
        lastWorkspaceId: null,
      },
      environmentDefaults: {},
    };
  }

  return {
    version: 3,
    general: {
      defaultRoute: isDefaultRoute(settings.general.defaultRoute)
        ? settings.general.defaultRoute
        : 'terminal',
      terminal: {
        fontSize: clampTerminalFontSize(settings.general.terminal.fontSize),
      },
      editor: {
        fontSize: editorFontSize,
        fontFamily: editorFontFamily,
      },
    },
    taskConfiguration: settings.taskConfiguration,
    projectDefaults: sanitizedProjectDefaults,
  };
}

export function SettingsProvider({ children }: ProviderProps) {
  const [state, setState] = useState<SettingsState>(() => readStoredSettings());
  const [activeProjectId, setActiveProjectId] = useState<string>('default');

  useEffect(() => {
    void getCodexDefaults().then((defaults) => {
      setState((current) => {
        const profileId = 'codex-app-server-default';
        const profiles = current.settings.taskConfiguration.researchAgentProfiles;
        const existing = profiles.find((profile) => profile.profileId === profileId);
        const nextCodexProfile = applyCodexDefaultsToProfile(
          existing ?? createCodexAppServerResearchAgentProfile(),
          {
            codexConfigToml: defaults.codex_config_toml,
            codexAuthJson: defaults.codex_auth_json,
          }
        );
        const nextProfiles = existing
          ? profiles.map((profile) =>
              profile.profileId === profileId ? nextCodexProfile : profile
            )
          : [...profiles, nextCodexProfile];
        return {
          ...current,
          settings: {
            ...current.settings,
            taskConfiguration: {
              ...current.settings.taskConfiguration,
              researchAgentProfiles: nextProfiles,
            },
          },
        };
      });
    });
  }, []);

  const commitSettings = (nextSettings: WebUiSettingsDocument): void => {
    const sanitized = sanitizeSettings(nextSettings);
    writeStoredSettings(sanitized);
    setState({
      settings: sanitized,
      recoveryReason: null,
    });
  };

  const value = useMemo<SettingsContextValue>(
    () => ({
      settings: state.settings,
      recoveryReason: state.recoveryReason,
      activeProjectId,
      setActiveProjectId,
      saveGeneralPreferences: (general) => {
        commitSettings({
          ...state.settings,
          general: {
            defaultRoute: general.defaultRoute,
            terminal: {
              fontSize: general.terminal.fontSize,
            },
            editor: {
              fontSize: general.editor.fontSize,
              fontFamily: general.editor.fontFamily,
            },
          },
        });
      },
      resetGeneralPreferences: () => {
        const defaults = createDefaultWebUiSettings();
        commitSettings({
          ...state.settings,
          general: defaults.general,
        });
      },
      saveTaskConfigurationSettings: (taskConfiguration) => {
        commitSettings({
          ...state.settings,
          taskConfiguration,
        });
      },
      resetTaskConfigurationSettings: () => {
        commitSettings({
          ...state.settings,
          taskConfiguration: createDefaultTaskConfigurationSettings(),
        });
      },
      saveResearchAgentProfile: (profile) => {
        const profiles = state.settings.taskConfiguration.researchAgentProfiles;
        const profileExists = profiles.some((item) => item.profileId === profile.profileId);
        commitSettings({
          ...state.settings,
          taskConfiguration: {
            ...state.settings.taskConfiguration,
            researchAgentProfiles: profileExists
              ? profiles.map((item) => (item.profileId === profile.profileId ? profile : item))
              : [...profiles, profile],
          },
        });
      },
      saveProjectDefaultEnvironment: (projectId, environmentId) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              defaultEnvironmentId: environmentId,
            },
          },
        });
      },
      saveProjectDefaultWorkspace: (projectId, workspaceId) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              defaultWorkspaceId: workspaceId,
            },
          },
        });
      },
      saveProjectEnvironmentDefaults: (projectId, environmentId, defaults) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              environmentDefaults: {
                ...currentProject.environmentDefaults,
                [environmentId]: {
                  titleTemplate: defaults.titleTemplate,
                  taskInputTemplate: defaults.taskInputTemplate,
                  researchAgentProfileId: defaults.researchAgentProfileId,
                  taskConfigurationId: defaults.taskConfigurationId,
                },
              },
            },
          },
        });
      },
      resetProjectEnvironmentDefaults: (projectId, environmentId) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        const nextEnvironmentDefaults = {
          ...currentProject.environmentDefaults,
        };
        delete nextEnvironmentDefaults[environmentId];

        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              environmentDefaults: nextEnvironmentDefaults,
            },
          },
        });
      },
      rememberSelectedEnvironment: (projectId, environmentId) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              selection: {
                ...currentProject.selection,
                lastEnvironmentId: environmentId,
              },
            },
          },
        });
      },
      rememberSelectedWorkspace: (projectId, workspaceId) => {
        const currentProject = getOrCreateProjectSettings(state.settings.projectDefaults, projectId);
        commitSettings({
          ...state.settings,
          projectDefaults: {
            ...state.settings.projectDefaults,
            [projectId]: {
              ...currentProject,
              selection: {
                ...currentProject.selection,
                lastWorkspaceId: workspaceId,
              },
            },
          },
        });
      },
      getProjectEnvironmentDefaults: (projectId, environmentId) =>
        resolveProjectEnvironmentDefaults(state.settings, projectId, environmentId),
    }),
    [state, activeProjectId]
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext);
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
  return {
    fontSize: settings.general.editor.fontSize,
    fontFamily: settings.general.editor.fontFamily,
  };
}

export function useProjectEnvironmentDefaults(
  projectId: string,
  environmentId: string | null
): EnvironmentTaskDefaults {
  return useSettings().getProjectEnvironmentDefaults(projectId, environmentId) ?? createEmptyEnvironmentTaskDefaults();
}
