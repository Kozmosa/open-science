import { describe, expect, it } from 'vitest';
import { messages } from '@/shared/i18n/messages';

function collectLeafPaths(value: unknown, prefix = ''): string[] {
  if (typeof value === 'string') {
    return [prefix];
  }

  if (typeof value !== 'object' || value === null) {
    return [];
  }

  return Object.entries(value).flatMap(([key, child]) =>
    collectLeafPaths(child, prefix ? `${prefix}.${key}` : key)
  );
}

describe('i18n message catalog', () => {
  it('keeps English and Chinese message keys in parity', () => {
    const enKeys = collectLeafPaths(messages.en).sort();
    const zhKeys = collectLeafPaths(messages.zh).sort();

    expect(zhKeys).toEqual(enKeys);
  });

  it('keeps the English catalog free of CJK copy', () => {
    const englishValues = collectLeafPaths(messages.en).map((path) => {
      return path.split('.').reduce<unknown>(
        (value, segment) => (value as Record<string, unknown>)[segment],
        messages.en,
      );
    });

    expect(englishValues.filter((value) => typeof value === 'string' && /[\u3400-\u9fff]/u.test(value))).toEqual([]);
  });
});
