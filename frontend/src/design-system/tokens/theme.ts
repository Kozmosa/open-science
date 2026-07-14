export const semanticToneClasses = {
  success: 'border-[var(--osci-color-success-border)] bg-[var(--osci-color-success-soft)] text-[var(--osci-color-success-foreground)]',
  warning: 'border-[var(--osci-color-warning-border)] bg-[var(--osci-color-warning-soft)] text-[var(--osci-color-warning-foreground)]',
  danger: 'border-[var(--osci-color-danger-border)] bg-[var(--osci-color-danger-soft)] text-[var(--osci-color-danger-foreground)]',
  info: 'border-[var(--osci-color-info-border)] bg-[var(--osci-color-info-soft)] text-[var(--osci-color-info-foreground)]',
  muted: 'border-[var(--osci-color-border)] bg-[var(--osci-color-surface-subtle)] text-[var(--osci-color-text-secondary)]',
} as const;

export const semanticDotClasses = {
  success: 'bg-[var(--osci-color-success)]',
  warning: 'bg-[var(--osci-color-warning)]',
  danger: 'bg-[var(--osci-color-danger)]',
  info: 'bg-[var(--osci-color-info)]',
  muted: 'bg-[var(--osci-color-text-muted)]',
} as const;

export type SemanticTone = keyof typeof semanticToneClasses;
