import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resetMockEnvironmentState } from './mock';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetMockEnvironmentState();
});

describe.skip('environment endpoints', () => {
  it('uses the mock transport when VITE_USE_MOCK is true', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true');

    const { createEnvironment, deleteEnvironment, detectEnvironment, getEnvironments, installEnvironmentCodeServer } =
      await import('./endpoints');

    await expect(getEnvironments()).resolves.toEqual({
      items: [
        expect.objectContaining({
          alias: 'localhost',
          is_seed: true,
        }),
      ],
    });

    const created = await createEnvironment({
      alias: 'gpu-lab',
      display_name: 'GPU Lab',
      host: 'gpu.example.com',
    });

    expect(created.alias).toBe('gpu-lab');
    expect(created.latest_detection).toBeNull();

    const detected = await detectEnvironment(created.id);
    expect(detected.latest_detection?.status).toBe('success');
    expect(detected.latest_detection?.summary).toContain('gpu-lab');

    const installed = await installEnvironmentCodeServer(created.id);
    expect(installed.environment.code_server_path).toContain('/bin/code-server');
    expect(installed.code_server_path).toBe(installed.environment.code_server_path);

    await expect(deleteEnvironment(created.id)).resolves.toBeUndefined();
    await expect(getEnvironments()).resolves.toEqual({
      items: [
        expect.objectContaining({
          alias: 'localhost',
          is_seed: true,
        }),
      ],
    });
  });

  it('uses the real api client when VITE_USE_MOCK is false', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false');

    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'env-1', alias: 'gpu-lab' }), {
        status: 200,
        headers: {
          'content-type': 'application/json',
        },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const { installEnvironmentCodeServer, updateEnvironment } = await import('./endpoints');
    await expect(updateEnvironment('env-1', { display_name: 'GPU Lab Updated' })).resolves.toEqual({
      id: 'env-1',
      alias: 'gpu-lab',
    });
    await installEnvironmentCodeServer('env-1');

    expect(fetchMock).toHaveBeenCalledWith('/api/environments/env-1', expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/environments/env-1/install-code-server',
      expect.any(Object)
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.method).toBe('PATCH');
  });
});
