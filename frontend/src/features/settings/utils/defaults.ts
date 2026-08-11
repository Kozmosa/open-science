import type {
  DefaultProjectSettings,
  DefaultRoute,
  WebUiSettingsDocument,
} from '@features/settings/types';

export const settingsStorageKey = 'openscience:webui-settings:test-user';
export const legacySettingsStorageKeys = ['openscience:webui-settings', 'scholar-agent:webui-settings'];
export function settingsStorageKeyForUser(userId: string): string {
  return `openscience:webui-settings:${userId}`;
}
export const defaultTerminalFontSize = 13;
export const minTerminalFontSize = 11;
export const maxTerminalFontSize = 18;
export const defaultEditorFontSize = 14;
export const minEditorFontSize = 10;
export const maxEditorFontSize = 24;
export const defaultEditorFontFamily = 'monospace';

const supportedDefaultRoutes: DefaultRoute[] = [
  'today',
  'projects',
  'terminal',
  'tasks',
  'workspaces',
  'environments',
];

export function isDefaultRoute(value: unknown): value is DefaultRoute {
  return typeof value === 'string' && supportedDefaultRoutes.includes(value as DefaultRoute);
}

export function clampTerminalFontSize(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return defaultTerminalFontSize;
  }

  const rounded = Math.round(value);
  return Math.min(maxTerminalFontSize, Math.max(minTerminalFontSize, rounded));
}

export function clampEditorFontSize(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return defaultEditorFontSize;
  }

  const rounded = Math.round(value);
  return Math.min(maxEditorFontSize, Math.max(minEditorFontSize, rounded));
}

export function createDefaultProjectSettings(): DefaultProjectSettings {
  return {
    defaultEnvironmentId: null,
    selection: {
      lastEnvironmentId: null,
    },
  };
}

export function createDefaultWebUiSettings(): WebUiSettingsDocument {
  return {
    version: 6,
    general: {
      defaultRoute: 'today',
      terminal: {
        fontSize: defaultTerminalFontSize,
      },
      editor: {
        fontSize: defaultEditorFontSize,
        fontFamily: defaultEditorFontFamily,
      },
      appearance: {
        theme: 'light',
        motionEnabled: true,
      },
    },
    projectDefaults: {
      default: createDefaultProjectSettings(),
    },
  };
}
