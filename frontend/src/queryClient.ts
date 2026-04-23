import { QueryClient, type DefaultOptions } from '@tanstack/react-query';

export const appQueryClientDefaultOptions = {
  queries: {
    staleTime: 5000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  },
} satisfies DefaultOptions;

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: appQueryClientDefaultOptions,
  });
}
