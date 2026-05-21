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
export const reproduceBaselineTaskConfigurationId = 'reproduce-baseline-default';
export const discoverIdeasTaskConfigurationId = 'discover-ideas-default';
export const validateIdeasTaskConfigurationId = 'validate-ideas-default';

const supportedDefaultRoutes: DefaultRoute[] = ['terminal', 'tasks', 'workspaces', 'environments'];

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
    skillModes: {},
    skillsPrompt: '',
    settingsJson: '{\n  "permissions": {\n    "allow": ["Read", "Grep"]\n  }\n}',
    apiBaseUrl: '',
    apiKey: '',
    defaultOpusModel: '',
    defaultSonnetModel: '',
    defaultHaikuModel: '',
    envOverrides: '',
    codexBaseUrl: '',
    codexApiKey: '',
    codexModel: '',
    codexAppServerCommand: '',
    codexApprovalPolicy: '',
    codexConfigToml: '',
    codexAuthJson: '',
    codexConfigTomlSource: 'custom',
    codexAuthJsonSource: 'custom',
  };
}

export function createKimiResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: 'kimi-claude-code-default',
    label: 'Kimi Claude Code Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: JSON.stringify(
      {
        env: {
          ANTHROPIC_AUTH_TOKEN: 'sk-xxxx',
          ANTHROPIC_BASE_URL: 'https://api.kimi.com/coding/',
          ENABLE_TOOL_SEARCH: 'false',
          ANTHROPIC_DEFAULT_HAIKU_MODEL: 'kimi-for-coding',
          ANTHROPIC_DEFAULT_SONNET_MODEL: 'kimi-for-coding',
          ANTHROPIC_DEFAULT_OPUS_MODEL: 'kimi-for-coding',
          CLAUDE_CODE_AUTO_COMPACT_WINDOW: '400000',
        },
        model: 'kimi-for-coding',
        skipDangerousModePermissionPrompt: true,
      },
      null,
      2
    ),
    apiBaseUrl: 'https://api.kimi.com/coding/',
    apiKey: '',
    defaultOpusModel: 'kimi-for-coding',
    defaultSonnetModel: 'kimi-for-coding',
    defaultHaikuModel: 'kimi-for-coding',
    envOverrides: '',
    codexBaseUrl: '',
    codexApiKey: '',
    codexModel: '',
    codexAppServerCommand: '',
    codexApprovalPolicy: '',
    codexConfigToml: '',
    codexAuthJson: '',
    codexConfigTomlSource: 'custom',
    codexAuthJsonSource: 'custom',
  };
}

export function createAgentSdkResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: 'agent-sdk-default',
    label: 'Claude Agent Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: '',
    apiBaseUrl: '',
    apiKey: '',
    defaultOpusModel: '',
    defaultSonnetModel: '',
    defaultHaikuModel: '',
    envOverrides: '',
    codexBaseUrl: '',
    codexApiKey: '',
    codexModel: '',
    codexAppServerCommand: '',
    codexApprovalPolicy: '',
    codexConfigToml: '',
    codexAuthJson: '',
    codexConfigTomlSource: 'custom',
    codexAuthJsonSource: 'custom',
  };
}

export function createCodexAppServerResearchAgentProfile(): ResearchAgentProfileSettings {
  return {
    profileId: 'codex-app-server-default',
    label: 'Codex App Server Default',
    systemPrompt: '',
    skills: [],
    skillModes: {},
    skillsPrompt: '',
    settingsJson: '',
    apiBaseUrl: '',
    apiKey: '',
    defaultOpusModel: '',
    defaultSonnetModel: '',
    defaultHaikuModel: '',
    envOverrides: '',
    codexBaseUrl: '',
    codexApiKey: '',
    codexModel: 'gpt-5-codex',
    codexAppServerCommand: 'codex app-server --listen stdio://',
    codexApprovalPolicy: 'never',
    codexConfigToml: '',
    codexAuthJson: '',
    codexConfigTomlSource: 'host_default',
    codexAuthJsonSource: 'host_default',
  };
}

export function applyCodexDefaultsToProfile(
  profile: ResearchAgentProfileSettings,
  defaults: {
    codexConfigToml?: string | null;
    codexAuthJson?: string | null;
  }
): ResearchAgentProfileSettings {
  return {
    ...profile,
    codexConfigToml:
      profile.codexConfigTomlSource === 'custom'
        ? profile.codexConfigToml
        : (defaults.codexConfigToml ?? ''),
    codexAuthJson:
      profile.codexAuthJsonSource === 'custom'
        ? profile.codexAuthJson
        : (defaults.codexAuthJson ?? ''),
    codexConfigTomlSource:
      profile.codexConfigTomlSource === 'custom' ? 'custom' : 'host_default',
    codexAuthJsonSource:
      profile.codexAuthJsonSource === 'custom' ? 'custom' : 'host_default',
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
    {
      configId: reproduceBaselineTaskConfigurationId,
      label: 'Reproduce Baseline',
      mode: 'reproduce_baseline',
    },
    {
      configId: discoverIdeasTaskConfigurationId,
      label: 'Discover IDEAs',
      mode: 'discover_ideas',
    },
    {
      configId: validateIdeasTaskConfigurationId,
      label: 'Validate IDEAs',
      mode: 'validate_ideas',
    },
  ];
}

export function createDefaultTaskConfigurationSettings(): TaskConfigurationSettings {
  return {
    defaultExecutionEngineId: 'claude-code',
    researchAgentProfiles: [
      createDefaultResearchAgentProfile(),
      createKimiResearchAgentProfile(),
      createAgentSdkResearchAgentProfile(),
      createCodexAppServerResearchAgentProfile(),
    ],
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
    version: 3,
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
