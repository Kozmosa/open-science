import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateOsciThemeManifest } from '@design-system';

function luminance(hex: string): number {
  const channels = hex.match(/[0-9a-f]{2}/gi)?.map((value) => Number.parseInt(value, 16) / 255) ?? [];
  const linear = channels.map((value) => value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return (linear[0] ?? 0) * 0.2126 + (linear[1] ?? 0) * 0.7152 + (linear[2] ?? 0) * 0.0722;
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return ((values[0] ?? 0) + 0.05) / ((values[1] ?? 0) + 0.05);
}

describe('osci design contract', () => {
  it('keeps the official text and canvas pairs above WCAG AA', () => {
    expect(contrast('#1d1d1f', '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('#515154', '#ffffff')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('#f5f5f7', '#0f0f10')).toBeGreaterThanOrEqual(4.5);
    expect(contrast('#d2d2d7', '#0f0f10')).toBeGreaterThanOrEqual(4.5);
  });

  it('mounts official themes through data-osci-theme and keeps the legacy alias baseline fixed', () => {
    const light = readFileSync(resolve(process.cwd(), 'src/design-system/tokens/themes/osci-light.css'), 'utf8');
    const dark = readFileSync(resolve(process.cwd(), 'src/design-system/tokens/themes/osci-dark.css'), 'utf8');
    const aliases = readFileSync(resolve(process.cwd(), 'src/design-system/tokens/prism-tokens.css'), 'utf8');
    expect(light).toContain(':root[data-osci-theme="light"]');
    expect(dark).toContain(':root[data-osci-theme="dark"]');
    expect(aliases.match(/^\s+--[a-z0-9-]+:/gm)).toHaveLength(86);
  });

  it('rejects executable or unknown third-party theme data', () => {
    expect(validateOsciThemeManifest({
      contract: 'osci-theme/v1',
      id: 'quiet-blue',
      name: 'Quiet Blue',
      mode: 'light',
      tokens: { '--osci-color-primary': '#2563eb' },
    }).valid).toBe(true);
    expect(validateOsciThemeManifest({
      contract: 'osci-theme/v1',
      id: 'unsafe',
      name: 'Unsafe',
      mode: 'light',
      tokens: { '--osci-color-primary': 'url(https://example.test/x)' },
    }).valid).toBe(false);
    expect(validateOsciThemeManifest({
      contract: 'osci-theme/v1',
      id: 'unknown',
      name: 'Unknown',
      mode: 'dark',
      tokens: { '--not-registered': '#000000' },
    }).valid).toBe(false);
  });
});
