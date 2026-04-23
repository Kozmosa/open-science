/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import {
  clampTerminalFontSize,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  isDefaultRoute,
} from './defaults';
import { readStoredSettings, resolveProjectEnvironmentDefaults, writeStoredSettings } from './storage';
import type {
  EnvironmentTaskDefaults,
  SettingsRecoveryReason,
  WebUiSettingsDocument,
} from './types';

interface SettingsContextValue {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
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
    version: 1,
    general: {
      defaultRoute: isDefaultRoute(settings.general.defaultRoute)
        ? settings.general.defaultRoute
        : 'terminal',
      terminal: {
        fontSize: clampTerminalFontSize(settings.general.terminal.fontSize),
      },
    },
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
