import { useSyncExternalStore } from 'react';

export type ResolvedOsciTheme = 'light' | 'dark';

function readTheme(): ResolvedOsciTheme {
  return typeof document !== 'undefined' && document.documentElement.dataset.osciTheme === 'dark'
    ? 'dark'
    : 'light';
}

function subscribe(onChange: () => void): () => void {
  if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') return () => undefined;
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-osci-theme'] });
  return () => observer.disconnect();
}

export function useResolvedOsciTheme(): ResolvedOsciTheme {
  return useSyncExternalStore(subscribe, readTheme, () => 'light');
}
