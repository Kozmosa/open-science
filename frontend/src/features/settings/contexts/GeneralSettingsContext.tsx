/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';
import type { SettingsRecoveryReason, WebUiSettingsDocument } from '@features/settings/types';

interface GeneralSettingsState {
  settings: WebUiSettingsDocument;
  recoveryReason: SettingsRecoveryReason | null;
}

interface GeneralSettingsActions {
  saveGeneralPreferences: (general: WebUiSettingsDocument['general']) => void;
  resetGeneralPreferences: () => void;
  saveAppearanceSettings: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  resetAppearanceSettings: () => void;
}

type GeneralSettingsContextValue = GeneralSettingsState & GeneralSettingsActions;

const GeneralSettingsContext = createContext<GeneralSettingsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  value: GeneralSettingsContextValue;
}

export function GeneralSettingsProvider({ children, value }: ProviderProps) {
  return (
    <GeneralSettingsContext.Provider value={value}>
      {children}
    </GeneralSettingsContext.Provider>
  );
}

export function useGeneralSettings(): GeneralSettingsContextValue {
  const context = useContext(GeneralSettingsContext);
  if (context === null) {
    throw new Error('useGeneralSettings must be used within a SettingsProvider');
  }
  return context;
}
