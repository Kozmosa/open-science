const API_BASE = '/api';

let _accessToken: string | null = null;
let _refreshPromise: Promise<string | null> | null = null;

export function setAccessToken(token: string | null) {
  _accessToken = token;
}

// NOTE: Refresh token stored in localStorage (XSS-vulnerable).
// For production, use httpOnly cookies with CSRF protection, and
// serve the frontend with a strict Content-Security-Policy header.
// Access token is memory-only.
export function getStoredRefreshToken(): string | null {
  return localStorage.getItem('ainrf.refresh_token');
}

export function setStoredRefreshToken(token: string | null) {
  if (token) {
    localStorage.setItem('ainrf.refresh_token', token);
  } else {
    localStorage.removeItem('ainrf.refresh_token');
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

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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

  const response = await fetch(url, init);

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
        if (!retryResponse.ok) {
          const retryData = await parseResponseBody(retryResponse);
          throw new ApiError(
            createErrorMessage(path, retryResponse, retryData),
            retryResponse.status,
            path,
            retryData,
          );
        }
        const retryBody = await parseResponseBody(retryResponse);
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
    throw new ApiError('Session expired', 401, path);
  }

  if (!response.ok) {
    const data = await parseResponseBody(response);
    throw new ApiError(createErrorMessage(path, response, data), response.status, path, data);
  }

  const data = await parseResponseBody(response);
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
