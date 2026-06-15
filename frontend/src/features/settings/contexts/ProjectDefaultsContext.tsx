/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';
import type { EnvironmentTaskDefaults } from '@features/settings/types';

interface ProjectDefaultsState {
  activeProjectId: string;
}

interface ProjectDefaultsActions {
  setActiveProjectId: (projectId: string) => void;
  saveProjectDefaultEnvironment: (projectId: string, environmentId: string | null) => void;
  saveProjectDefaultWorkspace: (projectId: string, workspaceId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    projectId: string,
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (projectId: string, environmentId: string) => void;
  rememberSelectedEnvironment: (projectId: string, environmentId: string | null) => void;
  rememberSelectedWorkspace: (projectId: string, workspaceId: string | null) => void;
  getProjectEnvironmentDefaults: (projectId: string, environmentId: string | null) => EnvironmentTaskDefaults;
}

type ProjectDefaultsContextValue = ProjectDefaultsState & ProjectDefaultsActions;

const ProjectDefaultsContext = createContext<ProjectDefaultsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  value: ProjectDefaultsContextValue;
}

export function ProjectDefaultsProvider({ children, value }: ProviderProps) {
  return (
    <ProjectDefaultsContext.Provider value={value}>
      {children}
    </ProjectDefaultsContext.Provider>
  );
}

export function useProjectDefaults(): ProjectDefaultsContextValue {
  const context = useContext(ProjectDefaultsContext);
  if (context === null) {
    throw new Error('useProjectDefaults must be used within a SettingsProvider');
  }
  return context;
}
