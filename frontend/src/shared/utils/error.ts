import { ApiError } from '@/shared/api/client';
import { resolveErrorCopy } from '@/shared/i18n';

export function extractErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.code) {
    const localized = resolveErrorCopy(error.code);
    if (localized) return localized;
  }
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return null;
}
