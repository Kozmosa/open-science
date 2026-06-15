import { useState, useRef, useCallback, useEffect } from 'react';
import { ArrowUp, Plus, Globe } from 'lucide-react';
import { useT } from '@/shared/i18n';
import ReasonIcon from './ReasonIcon';

interface ChatInputBarProps {
  onSubmit: (prompt: string) => Promise<unknown> | unknown;
  disabled?: boolean;
  scrollButtonVisible?: boolean;
  onScrollToBottom?: () => void;
}

export default function ChatInputBar({
  onSubmit,
  disabled = false,
  scrollButtonVisible = false,
  onScrollToBottom,
}: ChatInputBarProps) {
  const t = useT();
  const [value, setValue] = useState('');
  const [isComposing, setIsComposing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSend = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isComposing) return;
    try {
      await onSubmit(trimmed);
      setValue('');
      const el = textareaRef.current;
      if (el) el.style.height = 'auto';
    } catch {
      // Keep input on failure so user can retry.
    }
  }, [value, disabled, isComposing, onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend, isComposing]
  );

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  return (
    <div className="pointer-events-none bg-gradient-to-t from-[var(--surface)]/60 to-transparent pt-8 pb-3 z-10 transition-colors duration-300">
      <div className="relative max-w-[760px] mx-auto px-4 pointer-events-auto">
        {scrollButtonVisible && onScrollToBottom && (
          <button
            type="button"
            onClick={onScrollToBottom}
            className="absolute -top-12 left-1/2 -translate-x-1/2 bg-[var(--prism-glass)] border border-[var(--border)] w-8 h-8 rounded-full flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] shadow-[var(--shadow-sm)] transition-all z-20 cursor-pointer backdrop-blur-xl"
            aria-label={t('chat.scrollToBottom')}
          >
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 5v14M19 12l-7 7-7-7" />
            </svg>
          </button>
        )}

        <div className="relative bg-[var(--prism-glass)] backdrop-blur-xl backdrop-saturate-[180%] border border-[var(--border-strong)] focus-within:border-[var(--prism-primary-border)] focus-within:bg-[var(--surface)]/90 rounded-[28px] transition-all duration-300 shadow-[var(--shadow-input)] focus-within:shadow-[var(--shadow-pane)]">
          <textarea
            ref={textareaRef}
            className="w-full bg-transparent border-none outline-none focus-visible:outline-none resize-none py-4 px-6 pr-[60px] pb-[46px] text-sm placeholder:text-[var(--text-tertiary)] text-[var(--text)] block leading-relaxed max-h-[200px]"
            placeholder={t('chat.inputPlaceholder')}
            rows={1}
            value={value}
            disabled={disabled}
            style={{ outline: 'none' }}
            onCompositionStart={() => setIsComposing(true)}
            onCompositionEnd={() => setIsComposing(false)}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
          />

          <div className="absolute right-2 bottom-2">
            <button
              type="button"
              onClick={handleSend}
              disabled={disabled || !value.trim()}
              className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                value.trim() && !disabled
                  ? 'bg-[var(--prism-primary)] text-white hover:bg-[var(--prism-primary-hover)] hover:scale-105 active:scale-95 cursor-pointer shadow-[var(--shadow-sm)]'
                  : 'bg-[var(--bg-secondary)] text-[var(--text-tertiary)] cursor-not-allowed'
              }`}
              aria-label={t('chat.send')}
            >
              <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
            </button>
          </div>

          <div className="absolute left-4 bottom-2.5 flex items-center gap-1 text-[var(--text-tertiary)]">
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--prism-primary-soft)] hover:text-[var(--prism-primary)] rounded-lg transition-colors"
              aria-label={t('chat.attach')}
            >
              <Plus className="w-5 h-5" strokeWidth={1.8} />
            </button>
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--prism-primary-soft)] hover:text-[var(--prism-primary)] rounded-lg transition-colors"
              aria-label={t('chat.webSearch')}
            >
              <Globe className="w-5 h-5" strokeWidth={1.8} />
            </button>
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--prism-primary-soft)] hover:text-[var(--prism-primary)] rounded-lg transition-colors"
              aria-label={t('chat.reason')}
            >
              <ReasonIcon className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
