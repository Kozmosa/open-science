import { createContext } from 'react';
import type {
  DomainCapabilities,
  DomainCapabilityAvailability,
  DomainCapabilityName,
} from './types';

export interface DomainCapabilityContextValue {
  capabilities: DomainCapabilities | null;
  isLoading: boolean;
  error: Error | null;
  availability: (capability: DomainCapabilityName) => DomainCapabilityAvailability;
  refresh: () => Promise<unknown>;
}

export const DomainCapabilityContext = createContext<DomainCapabilityContextValue | null>(null);
