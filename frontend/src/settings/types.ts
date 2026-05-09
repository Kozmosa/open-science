export type DefaultRoute = 'projects' | 'terminal' | 'tasks' | 'workspaces' | 'environments';

export type ExecutionEngineId = 'claude-code' | 'kimi-claude-code' | 'agent-sdk';
export type SkillMode = 'disabled' | 'enabled' | 'auto';
export type TaskConfigurationMode = 'raw_prompt' | 'structured_research' | 'reproduce_baseline' | 'discover_ideas' | 'validate_ideas';

export interface ResearchAgentProfileSettings {
  profileId: string;
  label: string;
  systemPrompt: string;
  skills: string[];
  skillModes: Record<string, SkillMode>;
  skillsPrompt: string;
  settingsJson: string;
  apiBaseUrl: string;
  apiKey: string;
  defaultOpusModel: string;
  defaultSonnetModel: string;
  defaultHaikuModel: string;
  envOverrides: string;
}

export interface TaskConfigurationPreset {
  configId: string;
  label: string;
  mode: TaskConfigurationMode;
}

export interface EnvironmentTaskDefaults {
  titleTemplate: string;
  taskInputTemplate: string;
  researchAgentProfileId: string;
  taskConfigurationId: string;
}

export interface DefaultProjectSelectionState {
  lastEnvironmentId: string | null;
  lastWorkspaceId: string | null;
}

export interface DefaultProjectSettings {
  defaultEnvironmentId: string | null;
  defaultWorkspaceId: string | null;
  selection: DefaultProjectSelectionState;
  environmentDefaults: Record<string, EnvironmentTaskDefaults>;
}

export interface TaskConfigurationSettings {
  defaultExecutionEngineId: ExecutionEngineId;
  researchAgentProfiles: ResearchAgentProfileSettings[];
  taskConfigurations: TaskConfigurationPreset[];
  defaultResearchAgentProfileId: string;
  defaultTaskConfigurationId: string;
}

export interface WebUiSettingsDocument {
  version: 3;
  general: {
    defaultRoute: DefaultRoute;
    terminal: {
      fontSize: number;
    };
    editor: {
      fontSize: number;
      fontFamily: string;
    };
  };
  taskConfiguration: TaskConfigurationSettings;
  projectDefaults: Record<string, DefaultProjectSettings>;
}

export type SettingsRecoveryReason = 'invalid_document' | 'unsupported_version';
