export const semanticToneClasses = {
  success: 'border-[var(--success-border)] bg-[var(--success-soft)] text-[var(--success-foreground)]',
  warning: 'border-[var(--warning-border)] bg-[var(--warning-soft)] text-[var(--warning-foreground)]',
  danger: 'border-[var(--danger-border)] bg-[var(--danger-soft)] text-[var(--danger-foreground)]',
  info: 'border-[var(--info-border)] bg-[var(--info-soft)] text-[var(--info-foreground)]',
  muted: 'border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
} as const;

export const semanticDotClasses = {
  success: 'bg-[var(--success)]',
  warning: 'bg-[var(--warning)]',
  danger: 'bg-[var(--danger)]',
  info: 'bg-[var(--info)]',
  muted: 'bg-[var(--text-tertiary)]',
} as const;

export type SemanticTone = keyof typeof semanticToneClasses;
