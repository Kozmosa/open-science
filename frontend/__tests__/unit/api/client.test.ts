import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getStoredRefreshToken, setStoredRefreshToken } from '../../../src/shared/api/client';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe('api client', () => {
  it('migrates the legacy refresh token storage key', () => {
    window.localStorage.setItem('ainrf.refresh_token', 'legacy-refresh');

    expect(getStoredRefreshToken()).toBe('legacy-refresh');
    expect(window.localStorage.getItem('openscience.refresh_token')).toBe('legacy-refresh');
  });

  it('stores refresh tokens under the OpenScience key', () => {
    setStoredRefreshToken('new-refresh');

    expect(window.localStorage.getItem('openscience.refresh_token')).toBe('new-refresh');
    expect(window.localStorage.getItem('ainrf.refresh_token')).toBeNull();
  });

  it('injects the Bearer token when access token is set', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { api, setAccessToken } = await import('../../../src/shared/api/client');
    setAccessToken('test-jwt-token');
    await expect(api.get<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init).toBeDefined();
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-jwt-token');
  });

  it('does not inject Authorization header when no access token is set', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { api, setAccessToken } = await import('../../../src/shared/api/client');
    setAccessToken(null);
    await expect(api.get<{ status: string }>('/health')).resolves.toEqual({ status: 'ok' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(new Headers(init?.headers).get('Authorization')).toBeNull();
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

    const { ApiError, api } = await import('../../../src/shared/api/client');

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

    const { api } = await import('../../../src/shared/api/client');
    await expect(api.patch<{ id: string }>('/environments/env-1', { display_name: 'GPU Lab' })).resolves.toEqual({
      id: 'env-1',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.method).toBe('PATCH');
  });
});
