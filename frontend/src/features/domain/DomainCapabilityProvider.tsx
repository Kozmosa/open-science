import { useMemo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/shared/api/queryKeys';
import { getDomainCapabilities } from './api';
import { capabilityAvailability } from './capabilityAvailability';
import { DomainCapabilityContext, type DomainCapabilityContextValue } from './context';

export function DomainCapabilityProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: queryKeys.domain.capabilities,
    queryFn: getDomainCapabilities,
    staleTime: 15_000,
    retry: 1,
  });
  const value = useMemo<DomainCapabilityContextValue>(() => ({
    capabilities: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    availability: (capability) => capabilityAvailability(query.data ?? null, capability),
    refresh: query.refetch,
  }), [query.data, query.error, query.isLoading, query.refetch]);

  return (
    <DomainCapabilityContext.Provider value={value}>
      {children}
    </DomainCapabilityContext.Provider>
  );
}
