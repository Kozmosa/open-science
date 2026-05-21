import type { ReactNode } from 'react';

interface AccessItemRowProps {
  label: string;
  sublabel?: string;
  meta?: ReactNode;
  onRemove: () => void;
  removeLabel: string;
  disabled?: boolean;
}

export function AccessItemRow({ label, sublabel, meta, onRemove, removeLabel, disabled }: AccessItemRowProps) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg)] border border-[var(--border)] text-sm">
      <div>
        <span className="font-medium text-[var(--text)]">{label}</span>
        {sublabel && <span className="text-[var(--text-secondary)] ml-2">{sublabel}</span>}
      </div>
      <div className="flex items-center gap-3">
        {meta && <span className="text-xs text-[var(--text-secondary)]">{meta}</span>}
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          className="text-xs text-red-500 hover:text-red-600 disabled:opacity-50"
        >
          {removeLabel}
        </button>
      </div>
    </div>
  );
}
