const APP_USER_STORAGE_KEY = 'ainrf.app_user_id';

let cachedAppUserId: string | null = null;

function generateFallbackId(): string {
  return `ainrf-user-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

export function getAppUserId(): string {
  if (cachedAppUserId) {
    return cachedAppUserId;
  }

  if (typeof window === 'undefined') {
    cachedAppUserId = generateFallbackId();
    return cachedAppUserId;
  }

  const existing = window.localStorage.getItem(APP_USER_STORAGE_KEY)?.trim() ?? '';
  if (existing) {
    cachedAppUserId = existing;
    return cachedAppUserId;
  }

  const generated =
    typeof window.crypto?.randomUUID === 'function'
      ? window.crypto.randomUUID()
      : generateFallbackId();
  window.localStorage.setItem(APP_USER_STORAGE_KEY, generated);
  cachedAppUserId = generated;
  return cachedAppUserId;
}
