import { getAppUserId } from './appUser';

const API_BASE = '/api';
const API_KEY = import.meta.env.VITE_AINRF_API_KEY?.trim() ?? '';

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

  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (API_KEY && !headers.has('X-API-Key')) {
    headers.set('X-API-Key', API_KEY);
  }

  if (!headers.has('X-AINRF-User-Id')) {
    headers.set('X-AINRF-User-Id', getAppUserId());
  }

  const init: RequestInit = {
    method: options.method ?? 'GET',
    headers,
  };

  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(url, init);

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
