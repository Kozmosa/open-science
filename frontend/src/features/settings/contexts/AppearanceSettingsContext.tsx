/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';
import type { WebUiSettingsDocument } from '@features/settings/types';

interface AppearanceSettingsState {
  appearance: WebUiSettingsDocument['general']['appearance'];
}

interface AppearanceSettingsActions {
  saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  resetAppearanceSettings: () => void;
}

type AppearanceSettingsContextValue = AppearanceSettingsState & AppearanceSettingsActions;

const AppearanceSettingsContext = createContext<AppearanceSettingsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  value: AppearanceSettingsContextValue;
}

export function AppearanceSettingsProvider({ children, value }: ProviderProps) {
  return (
    <AppearanceSettingsContext.Provider value={value}>
      {children}
    </AppearanceSettingsContext.Provider>
  );
}

export function useAppearanceSettings(): AppearanceSettingsContextValue {
  const context = useContext(AppearanceSettingsContext);
  if (context === null) {
    throw new Error('useAppearanceSettings must be used within a SettingsProvider');
  }
  return context;
}
