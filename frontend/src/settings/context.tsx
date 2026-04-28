/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  clampTerminalFontSize,
  createDefaultTaskConfigurationSettings,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  isDefaultRoute,
} from './defaults';
import { readStoredSettings, resolveProjectEnvironmentDefaults, writeStoredSettings } from './storage';
import type {
  EnvironmentTaskDefaults,
  ResearchAgentProfileSettings,
  SettingsRecoveryReason,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from './types';

interface SettingsContextValue {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveTaskConfigurationSettings: (taskConfiguration: TaskConfigurationSettings) => void;
  resetTaskConfigurationSettings: () => void;
  saveResearchAgentProfile: (profile: ResearchAgentProfileSettings) => void;
  saveProjectDefaultEnvironment: (environmentId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (environmentId: string) => void;
  rememberSelectedEnvironment: (environmentId: string | null) => void;
  getProjectEnvironmentDefaults: (environmentId: string | null) => EnvironmentTaskDefaults;
}

const SettingsContext = createContext<SettingsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

interface SettingsState {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
}

function sanitizeSettings(settings: WebUiSettingsDocument): WebUiSettingsDocument {
  return {
    version: 2,
    general: {
      defaultRoute: isDefaultRoute(settings.general.defaultRoute)
        ? settings.general.defaultRoute
        : 'terminal',
      terminal: {
        fontSize: clampTerminalFontSize(settings.general.terminal.fontSize),
      },
    },
    taskConfiguration: settings.taskConfiguration,
    projectDefaults: {
      default: {
        defaultEnvironmentId: settings.projectDefaults.default.defaultEnvironmentId,
        selection: {
          lastEnvironmentId: settings.projectDefaults.default.selection.lastEnvironmentId,
        },
        environmentDefaults: settings.projectDefaults.default.environmentDefaults,
      },
    },
  };
}

export function SettingsProvider({ children }: ProviderProps) {
  const [state, setState] = useState<SettingsState>(() => readStoredSettings());

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
      saveGeneralPreferences: (general) => {
        commitSettings({
          ...state.settings,
          general: {
            defaultRoute: general.defaultRoute,
            terminal: {
              fontSize: general.terminal.fontSize,
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
      saveProjectDefaultEnvironment: (environmentId) => {
        commitSettings({
          ...state.settings,
          projectDefaults: {
            default: {
              ...state.settings.projectDefaults.default,
              defaultEnvironmentId: environmentId,
            },
          },
        });
      },
      saveProjectEnvironmentDefaults: (environmentId, defaults) => {
        commitSettings({
          ...state.settings,
          projectDefaults: {
            default: {
              ...state.settings.projectDefaults.default,
              environmentDefaults: {
                ...state.settings.projectDefaults.default.environmentDefaults,
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
      resetProjectEnvironmentDefaults: (environmentId) => {
        const nextEnvironmentDefaults = {
          ...state.settings.projectDefaults.default.environmentDefaults,
        };
        delete nextEnvironmentDefaults[environmentId];

        commitSettings({
          ...state.settings,
          projectDefaults: {
            default: {
              ...state.settings.projectDefaults.default,
              environmentDefaults: nextEnvironmentDefaults,
            },
          },
        });
      },
      rememberSelectedEnvironment: (environmentId) => {
        commitSettings({
          ...state.settings,
          projectDefaults: {
            default: {
              ...state.settings.projectDefaults.default,
              selection: {
                lastEnvironmentId: environmentId,
              },
            },
          },
        });
      },
      getProjectEnvironmentDefaults: (environmentId) =>
        resolveProjectEnvironmentDefaults(state.settings, environmentId),
    }),
    [state]
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

export function useProjectEnvironmentDefaults(environmentId: string | null): EnvironmentTaskDefaults {
  return useSettings().getProjectEnvironmentDefaults(environmentId) ?? createEmptyEnvironmentTaskDefaults();
}
