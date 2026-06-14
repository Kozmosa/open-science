import { Copy, RotateCcw } from 'lucide-react';
import { useT } from '@/shared/i18n';
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

  const handleCopy = async () => {
    const text = message.content ?? '';
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Ignore copy failures.
    }
  };

  return (
    <div className="flex gap-4 max-w-full relative">
      <div className="w-8 h-8 rounded-full border border-[var(--border)] bg-[var(--surface)] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm transition-colors">
        <svg className="w-5 h-5 text-green-600 dark:text-green-500" viewBox="0 0 24 24" fill="currentColor">
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
          <div className="flex items-center gap-1.5 w-fit rounded-2xl bg-[var(--bg-secondary)] px-3 py-2 border border-[var(--border)] transition-colors">
            <div className="w-1.5 h-1.5 bg-[var(--text-secondary)] rounded-full animate-bounce [animation-delay:-0.3s]" />
            <div className="w-1.5 h-1.5 bg-[var(--text-secondary)] rounded-full animate-bounce [animation-delay:-0.15s]" />
            <div className="w-1.5 h-1.5 bg-[var(--text-secondary)] rounded-full animate-bounce" />
          </div>
        )}

        {message.aborted && (
          <div className="flex items-center space-x-[14px] text-[var(--text-tertiary)] mt-[-2px]">
            <button
              type="button"
              onClick={handleCopy}
              className="hover:text-[var(--text-secondary)] transition-colors"
              title={t('chat.copy')}
            >
              <Copy className="w-[15px] h-[15px]" />
            </button>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="hover:text-[var(--text-secondary)] transition-colors"
                title={t('chat.retry')}
              >
                <RotateCcw className="w-[15px] h-[15px]" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
