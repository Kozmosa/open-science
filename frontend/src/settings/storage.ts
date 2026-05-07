import {
  clampEditorFontSize,
  clampTerminalFontSize,
  createDefaultProjectSettings,
  createDefaultTaskConfigurationSettings,
  createDefaultWebUiSettings,
  createEmptyEnvironmentTaskDefaults,
  defaultEditorFontFamily,
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
        const skillsPrompt = typeof item.skillsPrompt === 'string' ? item.skillsPrompt : '';
        let skills: string[] = [];
        if (Array.isArray(item.skills)) {
          skills = item.skills.filter((s): s is string => typeof s === 'string');
        } else if (skillsPrompt.trim()) {
          // Backward compatibility: parse skillsPrompt into skills array
          skills = skillsPrompt
            .split(/[,\n]+/)
            .map((s) => s.trim())
            .filter((s) => s.length > 0);
        }

        // Normalize skillModes
        let skillModes: Record<string, 'disabled' | 'enabled' | 'auto'> = {};
        if (isRecord(item.skillModes)) {
          for (const [skillId, mode] of Object.entries(item.skillModes)) {
            if (mode === 'disabled' || mode === 'enabled' || mode === 'auto') {
              skillModes[skillId] = mode;
            }
          }
        } else {
          // Migrate from old skills[] array — not a fallback, just backward compat
          for (const skillId of skills) {
            skillModes[skillId] = 'enabled';
          }
        }

        // Derive skills from skillModes for backward compatibility
        const derivedSkills = Object.entries(skillModes)
          .filter(([, mode]) => mode === 'enabled')
          .map(([skillId]) => skillId);

        return [
          {
            profileId: item.profileId,
            label: item.label,
            systemPrompt: typeof item.systemPrompt === 'string' ? item.systemPrompt : '',
            skills: derivedSkills.length > 0 ? derivedSkills : skills,
            skillModes,
            skillsPrompt,
            settingsJson: typeof item.settingsJson === 'string' ? item.settingsJson : '',
          },
        ];
      })
    : defaults.researchAgentProfiles;
  if (!Array.isArray(value.researchAgentProfiles)) {
    hadFallback = true;
  }

  const normalizedTaskConfigurations = Array.isArray(value.taskConfigurations)
    ? value.taskConfigurations.flatMap((item): TaskConfigurationPreset[] => {
        if (
          !isRecord(item) ||
          typeof item.configId !== 'string' ||
          typeof item.label !== 'string' ||
          (item.mode !== 'raw_prompt' && item.mode !== 'structured_research' && item.mode !== 'reproduce_baseline' && item.mode !== 'discover_ideas' && item.mode !== 'validate_ideas')
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

  // Backfill missing default presets so new ARIS modes appear for existing users
  const existingIds = new Set(normalizedTaskConfigurations.map((c) => c.configId));
  const backfilledPresets = defaults.taskConfigurations.filter((preset) => !existingIds.has(preset.configId));
  const taskConfigurations = backfilledPresets.length > 0
    ? [...normalizedTaskConfigurations, ...backfilledPresets]
    : normalizedTaskConfigurations;

  return {
    taskConfiguration: {
      defaultExecutionEngineId:
        value.defaultExecutionEngineId === 'kimi-claude-code'
          ? 'kimi-claude-code'
          : 'claude-code',
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
  if (value.defaultEnvironmentId != null && defaultEnvironmentId === null) {
    hadFallback = true;
  }

  const defaultWorkspaceId = readStringOrNull(value.defaultWorkspaceId);
  if (value.defaultWorkspaceId != null && defaultWorkspaceId === null) {
    hadFallback = true;
  }

  const lastEnvironmentId = selection ? readStringOrNull(selection.lastEnvironmentId) : null;
  if (selection?.lastEnvironmentId != null && lastEnvironmentId === null) {
    hadFallback = true;
  }

  const lastWorkspaceId = selection ? readStringOrNull(selection.lastWorkspaceId) : null;
  if (selection?.lastWorkspaceId != null && lastWorkspaceId === null) {
    hadFallback = true;
  }

  return {
    projectSettings: {
      defaultEnvironmentId,
      defaultWorkspaceId,
      selection: {
        lastEnvironmentId,
        lastWorkspaceId,
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

  if (parsed.version !== 1 && parsed.version !== 2 && parsed.version !== 3) {
    return { settings: defaults, recoveryReason: 'unsupported_version' };
  }

  const general = isRecord(parsed.general) ? parsed.general : null;
  const projectDefaults = isRecord(parsed.projectDefaults) ? parsed.projectDefaults : null;
  if (general === null || projectDefaults === null) {
    return { settings: defaults, recoveryReason: 'invalid_document' };
  }

  // v2 → v3 migration: flatten projectDefaults.default into projectDefaults['default']
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

  const {
    taskConfiguration,
    hadFallback: hadTaskConfigurationFallback,
  } = normalizeTaskConfigurationSettings(
    parsed.version >= 2 ? parsed.taskConfiguration : createDefaultTaskConfigurationSettings()
  );

  let defaultRoute = isDefaultRoute(general.defaultRoute)
    ? general.defaultRoute
    : defaults.general.defaultRoute;
  // v2 → v3 migration: rename 'containers' route to 'environments'
  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
  if ((defaultRoute as string) === 'containers') {
    defaultRoute = 'environments';
  }

  const terminalSettings = isRecord(general.terminal) ? general.terminal : null;
  const terminalFontSize = clampTerminalFontSize(terminalSettings?.fontSize);
  const editorSettings = isRecord(general.editor) ? general.editor : null;
  const editorFontSize = clampEditorFontSize(editorSettings?.fontSize);
  const editorFontFamily =
    typeof editorSettings?.fontFamily === 'string' && editorSettings.fontFamily.length > 0
      ? editorSettings.fontFamily
      : defaultEditorFontFamily;

  const missingDefaultRoute = general.defaultRoute === undefined;
  const invalidDefaultRoute = general.defaultRoute !== undefined && !isDefaultRoute(general.defaultRoute);
  const missingTerminalSettings = terminalSettings === null || terminalSettings.fontSize === undefined;
  const invalidTerminalFontSize =
    terminalSettings?.fontSize !== undefined &&
    clampTerminalFontSize(terminalSettings.fontSize) !== terminalSettings.fontSize;
  const missingEditorSettings =
    parsed.version >= 2 && (editorSettings === null || editorSettings.fontSize === undefined);
  const invalidEditorFontSize =
    editorSettings?.fontSize !== undefined &&
    clampEditorFontSize(editorSettings.fontSize) !== editorSettings.fontSize;

  return {
    settings: {
      version: 3,
      general: {
        defaultRoute,
        terminal: {
          fontSize: terminalFontSize,
        },
        editor: {
          fontSize: editorFontSize,
          fontFamily: editorFontFamily,
        },
      },
      taskConfiguration,
      projectDefaults: projectDefaultsMap,
    },
    recoveryReason:
      hadProjectDefaultsMigration ||
      hadTaskConfigurationFallback ||
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

export function writeStoredSettings(settings: WebUiSettingsDocument): void {
  try {
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
  } catch {
    // Ignore storage failures and keep the settings in memory.
  }
}

export function resolveProjectEnvironmentDefaults(
  settings: WebUiSettingsDocument,
  projectId: string,
  environmentId: string | null
): EnvironmentTaskDefaults {
  if (environmentId === null) {
    return createEmptyEnvironmentTaskDefaults();
  }

  const projectSettings = settings.projectDefaults[projectId] ?? settings.projectDefaults.default;
  if (!projectSettings) {
    return createEmptyEnvironmentTaskDefaults();
  }

  return (
    projectSettings.environmentDefaults[environmentId] ??
    createEmptyEnvironmentTaskDefaults()
  );
}
