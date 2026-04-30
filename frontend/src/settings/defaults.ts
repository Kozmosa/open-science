import type {
  DefaultProjectSettings,
  DefaultRoute,
  EnvironmentTaskDefaults,
  ResearchAgentProfileSettings,
  TaskConfigurationPreset,
  TaskConfigurationSettings,
  WebUiSettingsDocument,
} from './types';

export const settingsStorageKey = 'scholar-agent:webui-settings';
export const defaultTerminalFontSize = 13;
export const minTerminalFontSize = 11;
export const maxTerminalFontSize = 18;
export const defaultEditorFontSize = 14;
export const minEditorFontSize = 10;
export const maxEditorFontSize = 24;
export const defaultEditorFontFamily = 'monospace';
export const defaultResearchAgentProfileId = 'claude-code-default';
export const rawPromptTaskConfigurationId = 'raw-prompt';
export const structuredResearchTaskConfigurationId = 'structured-research-default';

const supportedDefaultRoutes: DefaultRoute[] = ['terminal', 'tasks', 'workspaces', 'containers'];

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

export function createDefaultResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: defaultResearchAgentProfileId,
    label: 'Claude Code Default',
    systemPrompt: '',
    skills: [],
    skillsPrompt: '',
    settingsJson: '{\n  "permissions": {\n    "allow": ["Read", "Grep"]\n  }\n}',
  };
}

export function createDefaultTaskConfigurations(): TaskConfigurationPreset[] {
  return [
    {
      configId: rawPromptTaskConfigurationId,
      label: 'Raw Prompt',
      mode: 'raw_prompt',
    },
    {
      configId: structuredResearchTaskConfigurationId,
      label: 'Structured Research',
      mode: 'structured_research',
    },
  ];
}

export function createDefaultTaskConfigurationSettings(): TaskConfigurationSettings {
  return {
    defaultExecutionEngineId: 'claude-code',
    researchAgentProfiles: [createDefaultResearchAgentProfile()],
    taskConfigurations: createDefaultTaskConfigurations(),
    defaultResearchAgentProfileId,
    defaultTaskConfigurationId: rawPromptTaskConfigurationId,
  };
}

export function createEmptyEnvironmentTaskDefaults(): EnvironmentTaskDefaults {
  return {
    titleTemplate: '',
    taskInputTemplate: '',
    researchAgentProfileId: defaultResearchAgentProfileId,
    taskConfigurationId: rawPromptTaskConfigurationId,
  };
}

export function createDefaultProjectSettings(): DefaultProjectSettings {
  return {
    defaultEnvironmentId: null,
    defaultWorkspaceId: null,
    selection: {
      lastEnvironmentId: null,
      lastWorkspaceId: null,
    },
    environmentDefaults: {},
  };
}

export function createDefaultWebUiSettings(): WebUiSettingsDocument {
  return {
    version: 2,
    general: {
      defaultRoute: 'terminal',
      terminal: {
        fontSize: defaultTerminalFontSize,
      },
      editor: {
        fontSize: defaultEditorFontSize,
        fontFamily: defaultEditorFontFamily,
      },
    },
    taskConfiguration: createDefaultTaskConfigurationSettings(),
    projectDefaults: {
      default: createDefaultProjectSettings(),
    },
  };
}
