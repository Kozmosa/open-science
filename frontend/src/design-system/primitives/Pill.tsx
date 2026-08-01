import type { ReactNode } from 'react';

type Tone =
  | 'user'
  | 'assistant'
  | 'thinking'
  | 'tool-call'
  | 'tool-result'
  | 'system'
  | 'info'
  | 'success'
  | 'warning'
  | 'error';

const TONE_VARS: Record<Tone, { fg: string; bg: string; border: string }> = {
  user: {
    fg: 'var(--color-msg-user)',
    bg: 'var(--color-msg-user-fade)',
    border: 'var(--color-msg-user)',
  },
  assistant: {
    fg: 'var(--color-msg-assistant)',
    bg: 'var(--color-msg-assistant-fade)',
    border: 'var(--color-msg-assistant)',
  },
  thinking: {
    fg: 'var(--color-msg-thinking)',
    bg: 'var(--color-msg-thinking-fade)',
    border: 'var(--color-msg-thinking)',
  },
  'tool-call': {
    fg: 'var(--color-msg-tool-call)',
    bg: 'var(--color-msg-tool-call-fade)',
    border: 'var(--color-msg-tool-call)',
  },
  'tool-result': {
    fg: 'var(--color-msg-tool-result)',
    bg: 'var(--color-msg-tool-result-fade)',
    border: 'var(--color-msg-tool-result)',
  },
  system: {
    fg: 'var(--color-msg-system)',
    bg: 'var(--color-msg-system-fade)',
    border: 'var(--color-msg-system)',
  },
  info: {
    fg: 'var(--info-foreground)',
    bg: 'var(--info-soft)',
    border: 'var(--info)',
  },
  success: {
    fg: 'var(--success)',
    bg: 'var(--success-soft)',
    border: 'var(--success)',
  },
  warning: {
    fg: 'var(--warning-foreground)',
    bg: 'var(--warning-soft)',
    border: 'var(--warning)',
  },
  error: {
    fg: 'var(--danger-foreground)',
    bg: 'var(--danger-soft)',
    border: 'var(--danger)',
  },
};

interface PillProps {
  tone?: Tone;
  variant?: 'solid' | 'soft' | 'outline';
  children: ReactNode;
  className?: string;
}

export default function Pill({
  tone = 'system',
  variant = 'soft',
  children,
  className = '',
}: PillProps) {
  const vars = TONE_VARS[tone];
  const base =
    'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide';

  const variantStyles = {
    solid: { backgroundColor: vars.fg, color: 'var(--background)' },
    soft: { backgroundColor: vars.bg, color: vars.fg },
    outline: {
      backgroundColor: 'transparent',
      color: vars.fg,
      border: `1px solid ${vars.border}`,
    },
  };

  return (
    <span className={`${base} ${className}`} style={variantStyles[variant]}>
      {children}
    </span>
  );
}
