import { readMigratedLocalStorage, removeLocalStorage } from '@/shared/utils/storage';

const API_BASE = '/api';
const REFRESH_TOKEN_STORAGE_KEY = 'openscience.refresh_token';
const LEGACY_REFRESH_TOKEN_STORAGE_KEYS = ['ainrf.refresh_token'];


let _accessToken: string | null = null;
let _refreshPromise: Promise<string | null> | null = null;

// Track the last X-Request-ID for error correlation with server logs.
let _lastRequestId: string | null = null;
const DEV_LITERATURE_LOGGING =
  import.meta.env.DEV && import.meta.env.VITE_DEV_LOGGING === '1';

/** Return the most recent X-Request-ID received from the backend. */
export function getLastRequestId(): string | null {
  return _lastRequestId;
}

export function setAccessToken(token: string | null) {
  _accessToken = token;
}

// NOTE: Refresh token stored in localStorage (XSS-vulnerable).
// For production, use httpOnly cookies with CSRF protection, and
// serve the frontend with a strict Content-Security-Policy header.
// Access token is memory-only.
export function getStoredRefreshToken(): string | null {
  return readMigratedLocalStorage(REFRESH_TOKEN_STORAGE_KEY, LEGACY_REFRESH_TOKEN_STORAGE_KEYS);
}

export function setStoredRefreshToken(token: string | null) {
  if (token) {
    for (const legacyKey of LEGACY_REFRESH_TOKEN_STORAGE_KEYS) {
      localStorage.removeItem(legacyKey);
    }
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
  } else {
    removeLocalStorage(REFRESH_TOKEN_STORAGE_KEY, LEGACY_REFRESH_TOKEN_STORAGE_KEYS);
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: HeadersInit;
}

type RequestOverrides = Omit<RequestOptions, 'method' | 'body'>;

class ApiError extends Error {
  status: number;
  data?: unknown;
  path: string;

  constructor(message: string, status: number, path: string, data?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.data = data;
  }
}

function getErrorDetail(data: unknown): string | null {
  if (typeof data === 'string') {
    return data.trim() || null;
  }

  if (!data || typeof data !== 'object') {
    return null;
  }

  const record = data as Record<string, unknown>;
  for (const key of ['detail', 'message', 'error', 'title', 'reason']) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }

  return null;
}

async function parseResponseBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type') ?? '';
  const rawBody = await response.text().catch(() => '');

  if (!rawBody) {
    return null;
  }

  if (contentType.includes('application/json')) {
    try {
      return JSON.parse(rawBody) as unknown;
    } catch {
      return rawBody;
    }
  }

  return rawBody;
}

function createErrorMessage(path: string, response: Response, data: unknown): string {
  const detail = getErrorDetail(data);
  const statusLabel = response.statusText.trim() || 'Unknown Error';
  const baseMessage = `Request to ${path} failed with ${response.status} ${statusLabel}`;
  return detail ? `${baseMessage}: ${detail}` : baseMessage;
}

function isLiteraturePath(path: string): boolean {
  return path.startsWith('/literature');
}

function summarizeResponseData(data: unknown): Record<string, unknown> {
  if (data === null) return { type: 'null' };
  if (Array.isArray(data)) return { type: 'array', item_count: data.length };
  if (typeof data !== 'object') return { type: typeof data };

  const record = data as Record<string, unknown>;
  const items = record.items;
  return {
    type: 'object',
    keys: Object.keys(record).slice(0, 20),
    ...(Array.isArray(items) ? { item_count: items.length } : {}),
    ...(typeof record.status === 'string' ? { status: record.status } : {}),
  };
}

function logLiteratureRequest(
  method: string,
  path: string,
  details: {
    phase: 'start' | 'success' | 'failure';
    status?: number;
    requestId?: string | null;
    elapsedMs: number;
    retry?: boolean;
    response?: unknown;
    error?: string;
  },
): void {
  if (!DEV_LITERATURE_LOGGING || !isLiteraturePath(path)) return;
  const payload = {
    method,
    path,
    ...details,
    elapsed_ms: Math.round(details.elapsedMs * 10) / 10,
    response: details.response === undefined ? undefined : summarizeResponseData(details.response),
  };
  delete (payload as Record<string, unknown>).elapsedMs;
  if (details.phase === 'failure') {
    console.warn('[OpenScience] literature request', payload);
  } else {
    console.debug('[OpenScience] literature request', payload);
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (import.meta.env.DEV) {
    const { assertTransportRequest } = await import('./transport');
    assertTransportRequest(options.method ?? 'GET', path);
  }
  const url = `${API_BASE}${path}`;
  const headers = new Headers(options.headers);

  if (options.body instanceof FormData) {
    // Let the browser set Content-Type with multipart boundary
  } else if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (_accessToken) {
    headers.set('Authorization', `Bearer ${_accessToken}`);
  }

  const init: RequestInit = {
    method: options.method ?? 'GET',
    headers,
  };

  if (options.body !== undefined) {
    init.body = options.body instanceof FormData ? options.body : JSON.stringify(options.body);
  }

  const method = options.method ?? 'GET';
  const startedAt = performance.now();
  logLiteratureRequest(method, path, { phase: 'start', elapsedMs: 0 });
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    logLiteratureRequest(method, path, {
      phase: 'failure',
      elapsedMs: performance.now() - startedAt,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }

  // Capture request ID for error correlation.
  const reqId = response.headers.get('x-request-id');
  if (reqId) {
    _lastRequestId = reqId;
  }

  // Auto-refresh on 401 (unless already on auth endpoints)
  if (response.status === 401 && path !== '/auth/refresh' && path !== '/auth/login') {
    const refreshToken = getStoredRefreshToken();
    if (refreshToken) {
      // Share a single refresh attempt across concurrent 401 responses
      if (!_refreshPromise) {
        _refreshPromise = (async () => {
          try {
            const refreshResp = await fetch(`${API_BASE}/auth/refresh`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (refreshResp.ok) {
              const refreshData = (await parseResponseBody(refreshResp)) as Record<string, unknown>;
              return (refreshData?.access_token as string) ?? null;
            }
            return null;
          } catch {
            return null;
          }
        })();
      }
      const newToken = await _refreshPromise;
      _refreshPromise = null;
      if (newToken) {
        setAccessToken(newToken);
        headers.set('Authorization', `Bearer ${newToken}`);
        const retryResponse = await fetch(url, init);
        const retryReqId = retryResponse.headers.get('x-request-id');
        if (retryReqId) {
          _lastRequestId = retryReqId;
        }
        if (!retryResponse.ok) {
          const retryData = await parseResponseBody(retryResponse);
          logLiteratureRequest(method, path, {
            phase: 'failure',
            status: retryResponse.status,
            requestId: retryReqId,
            elapsedMs: performance.now() - startedAt,
            retry: true,
            response: retryData,
            error: createErrorMessage(path, retryResponse, retryData),
          });
          throw new ApiError(
            createErrorMessage(path, retryResponse, retryData),
            retryResponse.status,
            path,
            retryData,
          );
        }
        const retryBody = await parseResponseBody(retryResponse);
        logLiteratureRequest(method, path, {
          phase: 'success',
          status: retryResponse.status,
          requestId: retryReqId,
          elapsedMs: performance.now() - startedAt,
          retry: true,
          response: retryBody,
        });
        return retryBody as T;
      }
    }
    // Refresh failed or no token — clear and redirect
    setAccessToken(null);
    setStoredRefreshToken(null);
    _refreshPromise = null;
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      window.location.href = '/login';
    }
    logLiteratureRequest(method, path, {
      phase: 'failure',
      status: 401,
      requestId: reqId,
      elapsedMs: performance.now() - startedAt,
      error: 'Session expired',
    });
    throw new ApiError('Session expired', 401, path);
  }

  if (!response.ok) {
    const data = await parseResponseBody(response);
    logLiteratureRequest(method, path, {
      phase: 'failure',
      status: response.status,
      requestId: reqId,
      elapsedMs: performance.now() - startedAt,
      response: data,
      error: createErrorMessage(path, response, data),
    });
    throw new ApiError(createErrorMessage(path, response, data), response.status, path, data);
  }

  const data = await parseResponseBody(response);
  logLiteratureRequest(method, path, {
    phase: 'success',
    status: response.status,
    requestId: reqId,
    elapsedMs: performance.now() - startedAt,
    response: data,
  });
  return data as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOverrides) => request<T>(path, options),
  post: <T>(path: string, body: unknown, options?: RequestOverrides) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body: unknown, options?: RequestOverrides) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body: unknown, options?: RequestOverrides) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOverrides) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};

export { ApiError };
