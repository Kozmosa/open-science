/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ReactNode } from 'react';
import type { LlmProvider } from '@features/settings/types';

interface LlmProvidersState {
  llmProviders: LlmProvider[];
}

interface LlmProvidersActions {
  saveLlmProvider: (provider: LlmProvider) => void;
  updateLlmProvider: (provider: LlmProvider) => void;
  deleteLlmProvider: (providerId: string) => void;
}

type LlmProvidersContextValue = LlmProvidersState & LlmProvidersActions;

const LlmProvidersContext = createContext<LlmProvidersContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
  value: LlmProvidersContextValue;
}

export function LlmProvidersProvider({ children, value }: ProviderProps) {
  return (
    <LlmProvidersContext.Provider value={value}>
      {children}
    </LlmProvidersContext.Provider>
  );
}

export function useLlmProviders(): LlmProvidersContextValue {
  const context = useContext(LlmProvidersContext);
  if (context === null) {
    throw new Error('useLlmProviders must be used within a SettingsProvider');
  }
  return context;
}
