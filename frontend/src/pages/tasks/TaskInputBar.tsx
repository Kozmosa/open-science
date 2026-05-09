import { useState, useCallback, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import { useT } from '../../i18n';

interface Props {
  onSubmit: (prompt: string) => Promise<unknown>;
  disabled?: boolean;
}

export default function TaskInputBar({ onSubmit, disabled }: Props) {
  const t = useT();
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  const handleSubmit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    try {
      await onSubmit(trimmed);
      setValue('');
    } catch {
      // Keep input on failure so user can retry
    }
  }, [value, disabled, onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  return (
    <div className="flex items-end gap-2 border-t border-[var(--border)] bg-[var(--bg)] p-3">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('pages.tasks.inputPlaceholder')}
        rows={1}
        disabled={disabled}
        className="min-h-[40px] flex-1 resize-none rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] disabled:opacity-50"
      />
      <button
        onClick={handleSubmit}
        disabled={disabled || !value.trim()}
        className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--apple-blue)] text-white transition hover:opacity-90 disabled:opacity-50"
      >
        <Send size={16} />
      </button>
    </div>
  );
}
