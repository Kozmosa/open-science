import { beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
});

describe('OpenScience Vite proxy', () => {
  it('shares the same proxy rules between dev server and preview', async () => {
    vi.stubEnv('OPENSCIENCE_WEBUI_API_KEY', 'proxy-secret');

    const { default: viteConfig } = await import('../../../vite.config');
    const { sharedOpenScienceProxyConfig } = await import('../../../vite.proxy');

    expect(viteConfig.server?.proxy).toBe(sharedOpenScienceProxyConfig);
    expect(viteConfig.preview?.proxy).toBe(sharedOpenScienceProxyConfig);
    expect(Object.keys(sharedOpenScienceProxyConfig)).toEqual(['/api', '/code', '/terminal']);
    expect(sharedOpenScienceProxyConfig['/api'].changeOrigin).toBe(false);
    expect(sharedOpenScienceProxyConfig['/code'].changeOrigin).toBe(false);
    expect(sharedOpenScienceProxyConfig['/terminal'].changeOrigin).toBe(false);
    expect(sharedOpenScienceProxyConfig['/terminal'].ws).toBe(true);
  });

  it('injects X-API-Key into proxied http and websocket requests', async () => {
    vi.stubEnv('OPENSCIENCE_WEBUI_API_KEY', 'proxy-secret');

    const { sharedOpenScienceProxyConfig } = await import('../../../vite.proxy');
    const handlers: Record<string, (...args: unknown[]) => void> = {};
    const terminalProxy = sharedOpenScienceProxyConfig['/terminal'];
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

  it('keeps the legacy API key environment variable as a compatibility fallback', async () => {
    vi.stubEnv('AINRF_WEBUI_API_KEY', 'legacy-proxy-secret');

    const { sharedOpenScienceProxyConfig } = await import('../../../vite.proxy');
    const handlers: Record<string, (...args: unknown[]) => void> = {};
    const apiProxy = sharedOpenScienceProxyConfig['/api'];
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

    apiProxy.configure?.(
      fakeProxy as unknown as Parameters<NonNullable<typeof apiProxy.configure>>[0],
      apiProxy
    );
    handlers.proxyReq?.(proxyRequest);

    expect(proxyRequestHeaders.get('X-API-Key')).toBe('legacy-proxy-secret');
  });

  it('rewrites only /api requests and keeps /code plus /terminal paths intact', async () => {
    const { sharedOpenScienceProxyConfig } = await import('../../../vite.proxy');

    expect(sharedOpenScienceProxyConfig['/api'].rewrite?.('/api/health')).toBe('/health');
    expect(sharedOpenScienceProxyConfig['/code'].rewrite).toBeUndefined();
    expect(sharedOpenScienceProxyConfig['/terminal'].rewrite).toBeUndefined();
  });
});
