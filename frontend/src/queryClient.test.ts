import { describe, expect, it } from 'vitest';
import { createAppQueryClient } from './queryClient';

describe('createAppQueryClient', () => {
  it('disables global auto-refetch noise while keeping stale caching', () => {
    const client = createAppQueryClient();
    const options = client.getDefaultOptions();

    expect(options.queries?.staleTime).toBe(5000);
    expect(options.queries?.refetchInterval).toBeUndefined();
    expect(options.queries?.refetchOnWindowFocus).toBe(false);
    expect(options.queries?.refetchOnReconnect).toBe(false);
  });
});
