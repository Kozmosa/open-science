import { Check, Copy, RotateCcw } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useT } from '@/shared/i18n';
import { copyText } from '@/shared/utils/clipboard';
import { useToast } from '@design-system';
import SafeMarkdown from '../messages/SafeMarkdown';
import ChatThinkingBlock from './ChatThinkingBlock';
import ChatToolCallGroup from './ChatToolCallGroup';
import type { ChatAssistantMessage as ChatAssistantMessageType } from './types';

interface ChatAssistantMessageProps {
  message: ChatAssistantMessageType;
  onRetry?: () => void;
}

export default function ChatAssistantMessage({ message, onRetry }: ChatAssistantMessageProps) {
  const t = useT();
  const { showToast } = useToast();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    const text = message.content ?? '';
    const result = await copyText(text);
    if (result.success) {
      setCopied(true);
      showToast(t('chat.copySuccess'), 'success');
      setTimeout(() => setCopied(false), 2000);
    } else {
      showToast(t('chat.copyError'), 'error');
    }
  }, [message.content, showToast, t]);

  return (
    <div className="group flex gap-4 max-w-full relative">
      <div className="w-8 h-8 rounded-full border border-[var(--border)] bg-[var(--color-msg-assistant-fade)] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm transition-colors">
        <svg className="w-5 h-5 text-[var(--color-msg-assistant)]" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" />
        </svg>
      </div>
      <div className="flex flex-col gap-4 w-full min-w-0">
        {message.thinking && <ChatThinkingBlock content={message.thinking} />}

        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="flex flex-col gap-1 w-full">
            <ChatToolCallGroup calls={message.toolCalls} />
          </div>
        )}

        {message.content && (
          <div className="text-sm leading-relaxed text-[var(--text)] w-full break-words">
            <SafeMarkdown content={message.content} />
          </div>
        )}

        {message.isStreaming && (
          <div className="flex items-center gap-1.5 w-fit rounded-2xl bg-[var(--color-msg-assistant-fade)] px-3 py-2 border border-[var(--border)] transition-colors">
            <div className="w-1.5 h-1.5 bg-[var(--color-msg-assistant)] rounded-full animate-bounce [animation-delay:-0.3s]" />
            <div className="w-1.5 h-1.5 bg-[var(--color-msg-assistant)] rounded-full animate-bounce [animation-delay:-0.15s]" />
            <div className="w-1.5 h-1.5 bg-[var(--color-msg-assistant)] rounded-full animate-bounce" />
          </div>
        )}

        <div className="flex items-center gap-1.5 text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={handleCopy}
            className="p-1 rounded-md hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors"
            title={copied ? '✓' : t('chat.copy')}
            aria-label={t('chat.copy')}
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[var(--success)]" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          {message.aborted && onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="p-1 rounded-md hover:text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] transition-colors"
              title={t('chat.retry')}
              aria-label={t('chat.retry')}
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
