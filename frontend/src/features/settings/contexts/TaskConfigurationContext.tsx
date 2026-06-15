/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';
import type {
  ResearchAgentProfileSettings,
  TaskConfigurationSettings,
} from '@features/settings/types';

interface TaskConfigurationState {
  taskConfiguration: TaskConfigurationSettings;
}

interface TaskConfigurationActions {
  saveTaskConfigurationSettings: (taskConfiguration: TaskConfigurationSettings) => void;
  resetTaskConfigurationSettings: () => void;
  saveResearchAgentProfile: (profile: ResearchAgentProfileSettings) => void;
}

type TaskConfigurationContextValue = TaskConfigurationState & TaskConfigurationActions;

const TaskConfigurationContext = createContext<TaskConfigurationContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  value: TaskConfigurationContextValue;
}

export function TaskConfigurationProvider({ children, value }: ProviderProps) {
  return (
    <TaskConfigurationContext.Provider value={value}>
      {children}
    </TaskConfigurationContext.Provider>
  );
}

export function useTaskConfiguration(): TaskConfigurationContextValue {
  const context = useContext(TaskConfigurationContext);
  if (context === null) {
    throw new Error('useTaskConfiguration must be used within a SettingsProvider');
  }
  return context;
}
