import type { ProxyOptions } from 'vite';

const DEFAULT_BACKEND_TARGET = 'http://127.0.0.1:8000';
const OPENSCIENCE_WEBUI_API_KEY = process.env.OPENSCIENCE_WEBUI_API_KEY?.trim() || process.env.AINRF_WEBUI_API_KEY?.trim() || '';
const OPENSCIENCE_WEBUI_BACKEND_TARGET = process.env.OPENSCIENCE_WEBUI_BACKEND_TARGET?.trim() || process.env.AINRF_WEBUI_BACKEND_TARGET?.trim() || DEFAULT_BACKEND_TARGET;

type ProxyHeaderTarget = {
  setHeader(name: string, value: string): void;
};

type ProxyEventHandler = (...args: unknown[]) => void;

type ProxyEventRegistrar = {
  on(event: 'proxyReq' | 'proxyReqWs', handler: ProxyEventHandler): void;
};

function isProxyHeaderTarget(value: unknown): value is ProxyHeaderTarget {
  return typeof value === 'object' && value !== null && 'setHeader' in value && typeof value.setHeader === 'function';
}

function injectApiKeyHeader(proxyRequest: unknown, apiKey: string): void {
  if (!apiKey || !isProxyHeaderTarget(proxyRequest)) {
    return;
  }
  proxyRequest.setHeader('X-API-Key', apiKey);
}

export function attachApiKeyProxyHooks(proxy: ProxyEventRegistrar, apiKey: string): void {
  if (!apiKey) {
    return;
  }
  proxy.on('proxyReq', (proxyRequest: unknown) => {
    injectApiKeyHeader(proxyRequest, apiKey);
  });
  proxy.on('proxyReqWs', (proxyRequest: unknown) => {
    injectApiKeyHeader(proxyRequest, apiKey);
  });
}

function createProxyRule(pathPrefix: '/api' | '/code' | '/terminal'): ProxyOptions {
  const rule: ProxyOptions = {
    target: OPENSCIENCE_WEBUI_BACKEND_TARGET,
    changeOrigin: false,
    configure(proxy) {
      attachApiKeyProxyHooks(proxy as ProxyEventRegistrar, OPENSCIENCE_WEBUI_API_KEY);
    },
  };

  if (pathPrefix === '/api') {
    rule.rewrite = (path) => path.replace(/^\/api/, '');
  }
  if (pathPrefix === '/terminal') {
    rule.ws = true;
  }
  return rule;
}

export const sharedAinrfProxyConfig: Record<string, ProxyOptions> = {
  '/api': createProxyRule('/api'),
  '/code': createProxyRule('/code'),
  '/terminal': createProxyRule('/terminal'),
};
