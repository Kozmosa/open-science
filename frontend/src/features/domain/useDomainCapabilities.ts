import { useContext } from 'react';
import { DomainCapabilityContext, type DomainCapabilityContextValue } from './context';

export function useDomainCapabilities(): DomainCapabilityContextValue {
  const value = useContext(DomainCapabilityContext);
  if (value === null) {
    throw new Error('useDomainCapabilities must be used within DomainCapabilityProvider');
  }
  return value;
}
