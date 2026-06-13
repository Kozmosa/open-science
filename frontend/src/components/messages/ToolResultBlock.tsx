import { memo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import SafeMarkdown from './SafeMarkdown';
import { accentColor, charCount, firstLine, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const ToolResultBlock = memo(function ToolResultBlock({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded === false);

  const raw = typeof message.content === 'string'
    ? message.content
    : JSON.stringify(message.content ?? '');
  const preview = firstLine(raw);

  return (
    <div className="my-1 pl-4">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-2 rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-1.5 text-left transition hover:bg-[var(--border)]"
        style={{ borderLeftColor: accentColor('tool_result') }}
      >
        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Pill tone="tool-result">{t('pages.tasks.messageType.toolResult')}</Pill>
        {!isOpen && (
          <span className="truncate text-xs text-[var(--text-secondary)]">{preview}</span>
        )}
        <span className="ml-auto shrink-0 text-xs text-[var(--text-tertiary)]">
          {charCount(raw)} · {timestamp}
        </span>
      </button>
      {isOpen && (
        <div
          className="mt-1 w-full rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-2"
          style={{ borderLeftColor: accentColor('tool_result') }}
        >
          {typeof message.content === 'string' ? (
            <SafeMarkdown content={message.content} className="text-xs text-[var(--text-secondary)]" />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(message.content, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
});
