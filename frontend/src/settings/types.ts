export type DefaultRoute = 'terminal' | 'tasks' | 'workspaces' | 'containers';

export interface EnvironmentTaskDefaults {
  titleTemplate: string;
  taskInputTemplate: string;
}

export interface DefaultProjectSelectionState {
  lastEnvironmentId: string | null;
}

export interface DefaultProjectSettings {
  defaultEnvironmentId: string | null;
  selection: DefaultProjectSelectionState;
  environmentDefaults: Record<string, EnvironmentTaskDefaults>;
}

export interface WebUiSettingsDocument {
  version: 1;
  general: {
    defaultRoute: DefaultRoute;
    terminal: {
      fontSize: number;
    };
  };
  projectDefaults: {
    default: DefaultProjectSettings;
  };
}

export type SettingsRecoveryReason = 'invalid_document' | 'unsupported_version';
