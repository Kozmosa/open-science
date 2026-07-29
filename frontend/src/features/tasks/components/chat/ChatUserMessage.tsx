import { Copy, Check } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useT } from '@/shared/i18n';
import { copyText } from '@/shared/utils/clipboard';
import { useToast } from '@design-system';
import type { ChatUserMessage as ChatUserMessageType } from './types';

interface ChatUserMessageProps {
  message: ChatUserMessageType;
}

export default function ChatUserMessage({ message }: ChatUserMessageProps) {
  const t = useT();
  const { showToast } = useToast();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    const result = await copyText(message.content);
    if (result.success) {
      setCopied(true);
      showToast(t('chat.copySuccess'), 'success');
      setTimeout(() => setCopied(false), 2000);
    } else {
      showToast(t('chat.copyError'), 'error');
    }
  }, [message.content, showToast, t]);

  return (
    <div className="group flex flex-col items-end">
      <div className="relative max-w-[85%] sm:max-w-[70%] bg-[var(--color-msg-user-fade)] border border-[var(--prism-primary-border)]/30 rounded-[24px] px-5 py-3 text-sm leading-relaxed text-[var(--text)] whitespace-pre-wrap break-words transition-colors">
        {message.content}
        <button
          type="button"
          onClick={handleCopy}
          className="absolute -bottom-1 right-0 translate-y-full opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)]"
          title={copied ? '✓' : t('chat.copy')}
          aria-label={t('chat.copy')}
        >
          {copied ? <Check className="w-3.5 h-3.5 text-[var(--success)]" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>
    </div>
  );
}
