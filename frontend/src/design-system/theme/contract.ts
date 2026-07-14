export const OSCI_THEME_CONTRACT = 'osci-theme/v1' as const;

export const OSCI_THEME_TOKEN_NAMES = [
  '--osci-color-canvas',
  '--osci-color-surface',
  '--osci-color-surface-subtle',
  '--osci-color-surface-elevated',
  '--osci-color-text',
  '--osci-color-text-secondary',
  '--osci-color-text-muted',
  '--osci-color-border-subtle',
  '--osci-color-border',
  '--osci-color-border-strong',
  '--osci-color-primary',
  '--osci-color-primary-hover',
  '--osci-color-primary-soft',
  '--osci-color-primary-border',
  '--osci-color-on-accent',
  '--osci-color-focus',
  '--osci-color-success',
  '--osci-color-warning',
  '--osci-color-danger',
  '--osci-color-info',
] as const;

export type OsciThemeTokenName = (typeof OSCI_THEME_TOKEN_NAMES)[number];

export interface OsciThemeManifestV1 {
  contract: typeof OSCI_THEME_CONTRACT;
  id: string;
  name: string;
  mode: 'light' | 'dark';
  author?: string;
  tokens: Partial<Record<OsciThemeTokenName, string>>;
}

export interface OsciThemeValidationResult {
  valid: boolean;
  errors: string[];
  manifest: OsciThemeManifestV1 | null;
}
