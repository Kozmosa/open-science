export type DefaultRoute = 'terminal' | 'tasks' | 'workspaces' | 'containers';

export type ExecutionEngineId = 'claude-code';
export type TaskConfigurationMode = 'raw_prompt' | 'structured_research';

export interface ResearchAgentProfileSettings {
  profileId: string;
  label: string;
  systemPrompt: string;
  skills: string[];
  skillsPrompt: string;
  settingsJson: string;
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
  version: 2;
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
  projectDefaults: {
    default: DefaultProjectSettings;
  };
}

export type SettingsRecoveryReason = 'invalid_document' | 'unsupported_version';
