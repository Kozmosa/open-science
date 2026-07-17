import type { ThemePreference } from '@features/settings/types';

export type ResolvedOsciTheme = 'light' | 'dark';

export function resolveOsciTheme(
  preference: ThemePreference,
  mediaQuery: Pick<MediaQueryList, 'matches'> | null = null,
): ResolvedOsciTheme {
  if (preference === 'system') return mediaQuery?.matches ? 'dark' : 'light';
  return preference;
}

export function applyOsciTheme(preference: ThemePreference): ResolvedOsciTheme {
  const mediaQuery = typeof window === 'undefined' || typeof window.matchMedia !== 'function'
    ? null
    : window.matchMedia('(prefers-color-scheme: dark)');
  const resolved = resolveOsciTheme(preference, mediaQuery);
  document.documentElement.dataset.osciTheme = resolved;
  return resolved;
}
