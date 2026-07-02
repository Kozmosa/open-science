import { readMigratedLocalStorage } from '@/shared/utils/storage';

const APP_USER_STORAGE_KEY = 'openscience.app_user_id';
const LEGACY_APP_USER_STORAGE_KEYS = ['ainrf.app_user_id'];

let cachedAppUserId: string | null = null;

function generateFallbackId(): string {
  return `openscience-user-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

export function getAppUserId(): string {
  if (cachedAppUserId) {
    return cachedAppUserId;
  }

  if (typeof window === 'undefined') {
    cachedAppUserId = generateFallbackId();
    return cachedAppUserId;
  }

  const existing = readMigratedLocalStorage(APP_USER_STORAGE_KEY, LEGACY_APP_USER_STORAGE_KEYS)?.trim() ?? '';
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
