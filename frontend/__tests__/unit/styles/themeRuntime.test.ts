import { describe, expect, it, vi } from 'vitest';
import { applyOsciTheme, resolveOsciTheme } from '@design-system';

describe('osci theme runtime', () => {
  it('resolves explicit and system preferences', () => {
    expect(resolveOsciTheme('light', { matches: true })).toBe('light');
    expect(resolveOsciTheme('dark', { matches: false })).toBe('dark');
    expect(resolveOsciTheme('system', { matches: true })).toBe('dark');
    expect(resolveOsciTheme('system', { matches: false })).toBe('light');
  });

  it('applies only the resolved official theme id to the document root', () => {
    const original = window.matchMedia;
    window.matchMedia = vi.fn(() => ({ matches: true })) as unknown as typeof window.matchMedia;
    expect(applyOsciTheme('system')).toBe('dark');
    expect(document.documentElement.dataset.osciTheme).toBe('dark');
    window.matchMedia = original;
  });
});
