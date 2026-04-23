import type {
  DefaultProjectSettings,
  DefaultRoute,
  EnvironmentTaskDefaults,
  WebUiSettingsDocument,
} from './types';

export const settingsStorageKey = 'scholar-agent:webui-settings';
export const defaultTerminalFontSize = 13;
export const minTerminalFontSize = 11;
export const maxTerminalFontSize = 18;

const supportedDefaultRoutes: DefaultRoute[] = ['terminal', 'tasks', 'workspaces', 'containers'];

export function isDefaultRoute(value: unknown): value is DefaultRoute {
  return (
    typeof value === 'string' &&
    supportedDefaultRoutes.includes(value as DefaultRoute)
  );
}

export function clampTerminalFontSize(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return defaultTerminalFontSize;
  }

  const rounded = Math.round(value);
  return Math.min(maxTerminalFontSize, Math.max(minTerminalFontSize, rounded));
}

export function createEmptyEnvironmentTaskDefaults(): EnvironmentTaskDefaults {
  return {
    titleTemplate: '',
    taskInputTemplate: '',
  };
}

export function createDefaultProjectSettings(): DefaultProjectSettings {
  return {
    defaultEnvironmentId: null,
    selection: {
      lastEnvironmentId: null,
    },
    environmentDefaults: {},
  };
}

export function createDefaultWebUiSettings(): WebUiSettingsDocument {
  return {
    version: 1,
    general: {
      defaultRoute: 'terminal',
      terminal: {
        fontSize: defaultTerminalFontSize,
      },
    },
    projectDefaults: {
      default: createDefaultProjectSettings(),
    },
  };
}
