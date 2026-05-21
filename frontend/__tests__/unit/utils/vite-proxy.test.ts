import { beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe('ainrf vite proxy', () => {
  it('shares the same proxy rules between dev server and preview', async () => {
    vi.stubEnv('AINRF_WEBUI_API_KEY', 'proxy-secret');

    const { default: viteConfig } = await import('../../../vite.config');
    const { sharedAinrfProxyConfig } = await import('../../../vite.proxy');

    expect(viteConfig.server?.proxy).toBe(sharedAinrfProxyConfig);
    expect(viteConfig.preview?.proxy).toBe(sharedAinrfProxyConfig);
    expect(Object.keys(sharedAinrfProxyConfig)).toEqual(['/api', '/code', '/terminal']);
    expect(sharedAinrfProxyConfig['/api'].changeOrigin).toBe(false);
    expect(sharedAinrfProxyConfig['/code'].changeOrigin).toBe(false);
    expect(sharedAinrfProxyConfig['/terminal'].changeOrigin).toBe(false);
    expect(sharedAinrfProxyConfig['/terminal'].ws).toBe(true);
  });

  it('injects X-API-Key into proxied http and websocket requests', async () => {
    vi.stubEnv('AINRF_WEBUI_API_KEY', 'proxy-secret');

    const { sharedAinrfProxyConfig } = await import('../../../vite.proxy');
    const handlers: Record<string, (...args: unknown[]) => void> = {};
    const terminalProxy = sharedAinrfProxyConfig['/terminal'];
    const proxyRequestHeaders = new Map<string, string>();
    const proxyRequest = {
      setHeader(name: string, value: string): void {
        proxyRequestHeaders.set(name, value);
      },
    };
    const fakeProxy = {
      on(event: string, handler: (...args: unknown[]) => void) {
        handlers[event] = handler;
        return this;
      },
    };

    terminalProxy.configure?.(
      fakeProxy as unknown as Parameters<NonNullable<typeof terminalProxy.configure>>[0],
      terminalProxy
    );
    handlers.proxyReq?.(proxyRequest);
    handlers.proxyReqWs?.(proxyRequest);

    expect(proxyRequestHeaders.get('X-API-Key')).toBe('proxy-secret');
  });

  it('rewrites only /api requests and keeps /code plus /terminal paths intact', async () => {
    const { sharedAinrfProxyConfig } = await import('../../../vite.proxy');

    expect(sharedAinrfProxyConfig['/api'].rewrite?.('/api/health')).toBe('/health');
    expect(sharedAinrfProxyConfig['/code'].rewrite).toBeUndefined();
    expect(sharedAinrfProxyConfig['/terminal'].rewrite).toBeUndefined();
  });
});
