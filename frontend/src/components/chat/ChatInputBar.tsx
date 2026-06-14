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
    <div className="pointer-events-none bg-gradient-to-t from-white/30 dark:from-[#1f1f1f]/30 to-transparent pt-10 pb-6 z-10 transition-colors duration-300">
      <div className="relative max-w-[760px] mx-auto px-4 pointer-events-auto">
        {scrollButtonVisible && onScrollToBottom && (
          <button
            type="button"
            onClick={onScrollToBottom}
            className="absolute -top-12 left-1/2 -translate-x-1/2 bg-white/50 dark:bg-[#2a2a2a]/50 border border-white/60 dark:border-white/10 w-8 h-8 rounded-full flex items-center justify-center text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-white/70 dark:hover:bg-[#333]/70 shadow-sm transition-all animate-in fade-in slide-in-from-bottom-2 z-20 cursor-pointer backdrop-blur-[12px]"
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

        <div className="relative bg-white/40 dark:bg-[#2a2a2a]/40 backdrop-blur-[32px] backdrop-saturate-[180%] border border-white/60 dark:border-white/10 focus-within:border-white/80 dark:focus-within:border-white/20 focus-within:bg-white/50 dark:focus-within:bg-[#333]/50 rounded-[28px] transition-all duration-300 shadow-[0_8px_32px_rgba(0,0,0,0.06),inset_0_1px_2px_rgba(255,255,255,0.8)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.2),inset_0_1px_2px_rgba(255,255,255,0.05)] focus-within:shadow-[0_12px_48px_rgba(0,0,0,0.1),inset_0_1px_2px_rgba(255,255,255,1)] dark:focus-within:shadow-[0_12px_48px_rgba(0,0,0,0.3),inset_0_1px_2px_rgba(255,255,255,0.1)]">
          <textarea
            ref={textareaRef}
            className="w-full bg-transparent border-none outline-none focus-visible:outline-none resize-none py-4 px-6 pr-[60px] pb-[46px] text-sm placeholder-gray-400 dark:placeholder-gray-500 text-[var(--text)] block leading-relaxed max-h-[200px]"
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
                  ? 'bg-[var(--text)] text-[var(--background)] hover:opacity-80 hover:scale-105 active:scale-95 cursor-pointer shadow-md'
                  : 'bg-black/5 dark:bg-white/5 text-black/20 dark:text-white/20 cursor-not-allowed'
              }`}
              aria-label={t('chat.send')}
            >
              <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
            </button>
          </div>

          <div className="absolute left-4 bottom-2.5 flex items-center gap-2 text-[var(--text-secondary)]">
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--bg-secondary)]/50 rounded-lg transition-colors"
              aria-label={t('chat.attach')}
            >
              <Plus className="w-5 h-5" strokeWidth={2} />
            </button>
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--bg-secondary)]/50 rounded-lg transition-colors"
              aria-label={t('chat.webSearch')}
            >
              <Globe className="w-5 h-5" strokeWidth={2} />
            </button>
            <button
              type="button"
              className="p-1.5 hover:bg-[var(--bg-secondary)]/50 rounded-lg transition-colors"
              aria-label={t('chat.reason')}
            >
              <ReasonIcon className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="text-center text-[11px] text-[var(--text-secondary)]/80 font-medium mt-3 transition-colors">
          {t('chat.disclaimer')}
        </div>
      </div>
    </div>
  );
}
