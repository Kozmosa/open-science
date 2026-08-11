import {
  clampEditorFontSize,
  clampTerminalFontSize,
  createDefaultProjectSettings,
  createDefaultWebUiSettings,
  defaultEditorFontFamily,
  isDefaultRoute,
  legacySettingsStorageKeys,
  settingsStorageKeyForUser,
} from '@features/settings/utils/defaults';
import { readMigratedLocalStorage } from '@/shared/utils/storage';
import type {
  DefaultProjectSettings,
  SettingsRecoveryReason,
  WebUiSettingsDocument,
} from '@features/settings/types';

interface SettingsLoadResult {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readStringOrNull(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function normalizeDefaultProjectSettings(
  value: unknown
): { projectSettings: DefaultProjectSettings; hadFallback: boolean } {
  const defaults = createDefaultProjectSettings();
  if (!isRecord(value)) {
    return { projectSettings: defaults, hadFallback: true };
  }

  let hadFallback = false;
  const selection = isRecord(value.selection) ? value.selection : null;
  if (selection === null) {
    hadFallback = true;
  }

  const defaultEnvironmentId = readStringOrNull(value.defaultEnvironmentId);
  if (value.defaultEnvironmentId != null && defaultEnvironmentId === null) {
    hadFallback = true;
  }

  const lastEnvironmentId = selection ? readStringOrNull(selection.lastEnvironmentId) : null;
  if (selection?.lastEnvironmentId != null && lastEnvironmentId === null) {
    hadFallback = true;
  }

  return {
    projectSettings: {
      defaultEnvironmentId,
      selection: {
        lastEnvironmentId,
      },
    },
    hadFallback,
  };
}

export function readStoredSettings(userId = 'test-user'): SettingsLoadResult {
  const defaults = createDefaultWebUiSettings();
  let rawValue: string | null = null;

  try {
    rawValue = readMigratedLocalStorage(settingsStorageKeyForUser(userId), legacySettingsStorageKeys);
  } catch {
    return { settings: defaults, recoveryReason: null };
  }

  if (rawValue === null) {
    return { settings: defaults, recoveryReason: null };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawValue) as unknown;
  } catch {
    return { settings: defaults, recoveryReason: 'invalid_document' };
  }

  if (!isRecord(parsed)) {
    return { settings: defaults, recoveryReason: 'invalid_document' };
  }

  if (![1, 2, 3, 4, 5, 6].includes(parsed.version as number)) {
    return { settings: defaults, recoveryReason: 'unsupported_version' };
  }

  const general = isRecord(parsed.general) ? parsed.general : null;
  const projectDefaults = isRecord(parsed.projectDefaults) ? parsed.projectDefaults : null;
  if (general === null || projectDefaults === null) {
    return { settings: defaults, recoveryReason: 'invalid_document' };
  }

  let projectDefaultsMap: Record<string, DefaultProjectSettings>;
  let hadProjectDefaultsMigration = false;
  if (parsed.version === 2) {
    const { projectSettings, hadFallback } = normalizeDefaultProjectSettings(projectDefaults.default);
    projectDefaultsMap = { default: projectSettings };
    hadProjectDefaultsMigration = hadFallback;
  } else {
    projectDefaultsMap = {};
    for (const [projectId, rawProjectSettings] of Object.entries(projectDefaults)) {
      const { projectSettings, hadFallback } = normalizeDefaultProjectSettings(rawProjectSettings);
      projectDefaultsMap[projectId] = projectSettings;
      hadProjectDefaultsMigration ||= hadFallback;
    }
    if (Object.keys(projectDefaultsMap).length === 0) {
      projectDefaultsMap = { default: createDefaultProjectSettings() };
    }
  }

  const hasLegacyContainersRoute = general.defaultRoute === 'containers';
  const defaultRoute = hasLegacyContainersRoute
    ? 'environments'
    : isDefaultRoute(general.defaultRoute)
      ? general.defaultRoute
      : defaults.general.defaultRoute;

  const terminalSettings = isRecord(general.terminal) ? general.terminal : null;
  const terminalFontSize = clampTerminalFontSize(terminalSettings?.fontSize);
  const editorSettings = isRecord(general.editor) ? general.editor : null;
  const editorFontSize = clampEditorFontSize(editorSettings?.fontSize);
  const editorFontFamily =
    typeof editorSettings?.fontFamily === 'string' && editorSettings.fontFamily.length > 0
      ? editorSettings.fontFamily
      : defaultEditorFontFamily;

  const appearanceSettings = isRecord(general.appearance) ? general.appearance : null;
  const theme =
    appearanceSettings?.theme === 'dark' || appearanceSettings?.theme === 'system'
      ? appearanceSettings.theme
      : 'light';
  const motionEnabled = appearanceSettings?.motionEnabled !== false;

  const missingDefaultRoute = general.defaultRoute === undefined;
  const invalidDefaultRoute =
    general.defaultRoute !== undefined &&
    !hasLegacyContainersRoute &&
    !isDefaultRoute(general.defaultRoute);
  const missingTerminalSettings =
    terminalSettings === null || terminalSettings.fontSize === undefined;
  const invalidTerminalFontSize =
    terminalSettings?.fontSize !== undefined &&
    clampTerminalFontSize(terminalSettings.fontSize) !== terminalSettings.fontSize;
  const missingEditorSettings =
    (parsed.version as number) >= 2 &&
    (editorSettings === null || editorSettings.fontSize === undefined);
  const invalidEditorFontSize =
    editorSettings?.fontSize !== undefined &&
    clampEditorFontSize(editorSettings.fontSize) !== editorSettings.fontSize;

  const settings: WebUiSettingsDocument = {
    version: 6,
    general: {
      defaultRoute,
      terminal: {
        fontSize: terminalFontSize,
      },
      editor: {
        fontSize: editorFontSize,
        fontFamily: editorFontFamily,
      },
      appearance: {
        theme,
        motionEnabled,
      },
    },
    projectDefaults: projectDefaultsMap,
  };

  if (parsed.version !== 6) {
    writeStoredSettings(settings, userId);
  }

  return {
    settings,
    recoveryReason:
      hadProjectDefaultsMigration ||
      missingDefaultRoute ||
      invalidDefaultRoute ||
      missingTerminalSettings ||
      invalidTerminalFontSize ||
      missingEditorSettings ||
      invalidEditorFontSize
        ? 'invalid_document'
        : null,
  };
}

export function writeStoredSettings(settings: WebUiSettingsDocument, userId = 'test-user'): void {
  try {
    window.localStorage.setItem(settingsStorageKeyForUser(userId), JSON.stringify(settings));
  } catch {
    // Ignore storage failures and keep the settings in memory.
  }
}
