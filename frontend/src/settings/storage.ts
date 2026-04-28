import {
  clampTerminalFontSize,
  createDefaultProjectSettings,
  createDefaultTaskConfigurationSettings,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  defaultResearchAgentProfileId,
  isDefaultRoute,
  rawPromptTaskConfigurationId,
  settingsStorageKey,
} from './defaults';
import type {
  DefaultProjectSettings,
  EnvironmentTaskDefaults,
  ResearchAgentProfileSettings,
  SettingsRecoveryReason,
  TaskConfigurationMode,
  TaskConfigurationPreset,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from './types';

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

function normalizeEnvironmentDefaults(
  value: unknown
): { environmentDefaults: Record<string, EnvironmentTaskDefaults>; hadFallback: boolean } {
  if (!isRecord(value)) {
    return { environmentDefaults: {}, hadFallback: true };
  }

  let hadFallback = false;
  const environmentDefaults: Record<string, EnvironmentTaskDefaults> = {};

  for (const [environmentId, item] of Object.entries(value)) {
    if (!isRecord(item)) {
      hadFallback = true;
      continue;
    }

    const titleTemplate = typeof item.titleTemplate === 'string' ? item.titleTemplate : null;
    const taskInputTemplate =
      typeof item.taskInputTemplate === 'string' ? item.taskInputTemplate : null;

    if (titleTemplate === null || taskInputTemplate === null) {
      hadFallback = true;
      continue;
    }

    environmentDefaults[environmentId] = {
      titleTemplate,
      taskInputTemplate,
      researchAgentProfileId:
        typeof item.researchAgentProfileId === 'string'
          ? item.researchAgentProfileId
          : defaultResearchAgentProfileId,
      taskConfigurationId:
        typeof item.taskConfigurationId === 'string'
          ? item.taskConfigurationId
          : rawPromptTaskConfigurationId,
    };
  }

  return { environmentDefaults, hadFallback };
}

function normalizeTaskConfigurationSettings(
  value: unknown
): { taskConfiguration: TaskConfigurationSettings; hadFallback: boolean } {
  const defaults = createDefaultTaskConfigurationSettings();
  if (!isRecord(value)) {
    return { taskConfiguration: defaults, hadFallback: true };
  }

  let hadFallback = false;
  const researchAgentProfiles = Array.isArray(value.researchAgentProfiles)
    ? value.researchAgentProfiles.flatMap((item): ResearchAgentProfileSettings[] => {
        if (!isRecord(item) || typeof item.profileId !== 'string' || typeof item.label !== 'string') {
          hadFallback = true;
          return [];
        }
        return [
          {
            profileId: item.profileId,
            label: item.label,
            systemPrompt: typeof item.systemPrompt === 'string' ? item.systemPrompt : '',
            skillsPrompt: typeof item.skillsPrompt === 'string' ? item.skillsPrompt : '',
            settingsJson: typeof item.settingsJson === 'string' ? item.settingsJson : '',
          },
        ];
      })
    : defaults.researchAgentProfiles;
  if (!Array.isArray(value.researchAgentProfiles)) {
    hadFallback = true;
  }

  const taskConfigurations = Array.isArray(value.taskConfigurations)
    ? value.taskConfigurations.flatMap((item): TaskConfigurationPreset[] => {
        if (
          !isRecord(item) ||
          typeof item.configId !== 'string' ||
          typeof item.label !== 'string' ||
          (item.mode !== 'raw_prompt' && item.mode !== 'structured_research')
        ) {
          hadFallback = true;
          return [];
        }
        return [
          {
            configId: item.configId,
            label: item.label,
            mode: item.mode as TaskConfigurationMode,
          },
        ];
      })
    : defaults.taskConfigurations;
  if (!Array.isArray(value.taskConfigurations)) {
    hadFallback = true;
  }

  return {
    taskConfiguration: {
      defaultExecutionEngineId: 'claude-code',
      researchAgentProfiles: researchAgentProfiles.length > 0 ? researchAgentProfiles : defaults.researchAgentProfiles,
      taskConfigurations: taskConfigurations.length > 0 ? taskConfigurations : defaults.taskConfigurations,
      defaultResearchAgentProfileId:
        typeof value.defaultResearchAgentProfileId === 'string'
          ? value.defaultResearchAgentProfileId
          : defaults.defaultResearchAgentProfileId,
      defaultTaskConfigurationId:
        typeof value.defaultTaskConfigurationId === 'string'
          ? value.defaultTaskConfigurationId
          : defaults.defaultTaskConfigurationId,
    },
    hadFallback,
  };
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

  const { environmentDefaults, hadFallback: hadEnvironmentFallback } = normalizeEnvironmentDefaults(
    value.environmentDefaults
  );
  hadFallback ||= hadEnvironmentFallback;

  const defaultEnvironmentId = readStringOrNull(value.defaultEnvironmentId);
  if (value.defaultEnvironmentId !== null && defaultEnvironmentId === null) {
    hadFallback = true;
  }

  const lastEnvironmentId = selection ? readStringOrNull(selection.lastEnvironmentId) : null;
  if (selection?.lastEnvironmentId !== null && lastEnvironmentId === null) {
    hadFallback = true;
  }

  return {
    projectSettings: {
      defaultEnvironmentId,
      selection: {
        lastEnvironmentId,
      },
      environmentDefaults,
    },
    hadFallback,
  };
}

export function readStoredSettings(): SettingsLoadResult {
  const defaults = createDefaultWebUiSettings();
  let rawValue: string | null = null;

  try {
    rawValue = window.localStorage.getItem(settingsStorageKey);
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

  if (parsed.version !== 1 && parsed.version !== 2) {
    return { settings: defaults, recoveryReason: 'unsupported_version' };
  }

  const general = isRecord(parsed.general) ? parsed.general : null;
  const projectDefaults = isRecord(parsed.projectDefaults) ? parsed.projectDefaults : null;
  if (general === null || projectDefaults === null) {
    return { settings: defaults, recoveryReason: 'invalid_document' };
  }

  const { projectSettings, hadFallback } = normalizeDefaultProjectSettings(projectDefaults.default);
  const {
    taskConfiguration,
    hadFallback: hadTaskConfigurationFallback,
  } = normalizeTaskConfigurationSettings(
    parsed.version === 2 ? parsed.taskConfiguration : createDefaultTaskConfigurationSettings()
  );

  const defaultRoute = isDefaultRoute(general.defaultRoute)
    ? general.defaultRoute
    : defaults.general.defaultRoute;
  const terminalSettings = isRecord(general.terminal) ? general.terminal : null;
  const fontSize = clampTerminalFontSize(terminalSettings?.fontSize);

  const missingDefaultRoute = general.defaultRoute === undefined;
  const invalidDefaultRoute = general.defaultRoute !== undefined && !isDefaultRoute(general.defaultRoute);
  const missingTerminalSettings = terminalSettings === null || terminalSettings.fontSize === undefined;
  const invalidTerminalFontSize =
    terminalSettings?.fontSize !== undefined &&
    clampTerminalFontSize(terminalSettings.fontSize) !== terminalSettings.fontSize;

  return {
    settings: {
      version: 2,
      general: {
        defaultRoute,
        terminal: {
          fontSize,
        },
      },
      taskConfiguration,
      projectDefaults: {
        default: projectSettings,
      },
    },
    recoveryReason:
      hadFallback ||
      hadTaskConfigurationFallback ||
      missingDefaultRoute ||
      invalidDefaultRoute ||
      missingTerminalSettings ||
      invalidTerminalFontSize
        ? 'invalid_document'
        : null,
  };
}

export function writeStoredSettings(settings: WebUiSettingsDocument): void {
  try {
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
  } catch {
    // Ignore storage failures and keep the settings in memory.
  }
}

export function resolveProjectEnvironmentDefaults(
  settings: WebUiSettingsDocument,
  environmentId: string | null
): EnvironmentTaskDefaults {
  if (environmentId === null) {
    return createEmptyEnvironmentTaskDefaults();
  }

  return (
    settings.projectDefaults.default.environmentDefaults[environmentId] ??
    createEmptyEnvironmentTaskDefaults()
  );
}
