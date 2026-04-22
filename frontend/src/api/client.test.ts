import { beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe('api client', () => {
  it('injects the configured API key header and app user id header', async () => {
    vi.stubEnv('VITE_AINRF_API_KEY', 'secret-key');
    window.localStorage.clear();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { api } = await import('./client');
    await expect(api.get<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init).toBeDefined();
    expect(new Headers(init?.headers).get('X-API-Key')).toBe('secret-key');
    expect(new Headers(init?.headers).get('X-AINRF-User-Id')).toBeTruthy();
  });

  it('preserves manually provided API key headers', async () => {
    vi.stubEnv('VITE_AINRF_API_KEY', 'env-secret');
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { api } = await import('./client');
    await expect(
      api.post<{ status: string }>('/health', { ok: true }, { headers: { 'X-API-Key': 'manual-secret' } })
    ).resolves.toEqual({ status: 'ok' });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(new Headers(init?.headers).get('X-API-Key')).toBe('manual-secret');
    expect(new Headers(init?.headers).get('X-AINRF-User-Id')).toBeTruthy();
  });

  it('surfaces server error details in ApiError', async () => {
    const response = {
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      headers: new Headers({
        'content-type': 'application/json',
      }),
      text: async () => JSON.stringify({ detail: 'terminal unavailable' }),
    } as Response;
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetchMock);

    const { ApiError, api } = await import('./client');

    try {
      await api.get('/terminal/session');
      throw new Error('expected request to fail');
    } catch (error: unknown) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({
        name: 'ApiError',
        status: 503,
        path: '/terminal/session',
        data: {
          detail: 'terminal unavailable',
        },
      });
      expect((error as Error).message).toBe(
        'Request to /terminal/session failed with 503 Service Unavailable: terminal unavailable'
      );
    }
  });

  it('supports PATCH requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'env-1' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { api } = await import('./client');
    await expect(api.patch<{ id: string }>('/environments/env-1', { display_name: 'GPU Lab' })).resolves.toEqual({
      id: 'env-1',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.method).toBe('PATCH');
  });
});
