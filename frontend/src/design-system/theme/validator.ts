import {
  OSCI_THEME_CONTRACT,
  OSCI_THEME_TOKEN_NAMES,
  type OsciThemeTokenName,
  type OsciThemeValidationResult,
} from './contract';

const tokenNames = new Set<string>(OSCI_THEME_TOKEN_NAMES);
const safeId = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const safeColor = /^(?:#[0-9a-f]{3,8}|(?:rgb|hsl)a?\([0-9.%\s,/-]+\)|transparent|currentColor)$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function safeTokenValue(value: string): boolean {
  return !/url\s*\(|expression\s*\(|javascript:|[{};]/i.test(value) && safeColor.test(value.trim());
}

export function validateOsciThemeManifest(value: unknown): OsciThemeValidationResult {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return { valid: false, errors: ['Theme manifest must be an object'], manifest: null };
  }
  if (value.contract !== OSCI_THEME_CONTRACT) errors.push('Unsupported theme contract');
  if (typeof value.id !== 'string' || !safeId.test(value.id)) errors.push('Theme id is invalid');
  if (typeof value.name !== 'string' || value.name.trim().length === 0) errors.push('Theme name is required');
  if (value.mode !== 'light' && value.mode !== 'dark') errors.push('Theme mode is invalid');
  if (value.author !== undefined && typeof value.author !== 'string') errors.push('Theme author is invalid');
  if (!isRecord(value.tokens)) {
    errors.push('Theme tokens must be an object');
  } else {
    for (const [name, tokenValue] of Object.entries(value.tokens)) {
      if (!tokenNames.has(name)) {
        errors.push(`Unknown theme token: ${name}`);
      } else if (typeof tokenValue !== 'string' || !safeTokenValue(tokenValue)) {
        errors.push(`Unsafe theme token value: ${name}`);
      }
    }
  }
  if (errors.length > 0) return { valid: false, errors, manifest: null };
  const tokens = Object.fromEntries(Object.entries(value.tokens as Record<string, string>)) as Partial<
    Record<OsciThemeTokenName, string>
  >;
  return {
    valid: true,
    errors: [],
    manifest: {
      contract: OSCI_THEME_CONTRACT,
      id: value.id as string,
      name: value.name as string,
      mode: value.mode as 'light' | 'dark',
      author: value.author as string | undefined,
      tokens,
    },
  };
}
