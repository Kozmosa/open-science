import { memo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import { accentColor, charCount, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const ThinkingBlock = memo(function ThinkingBlock({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded === false);
  const content = typeof message.content === 'string' ? message.content : '';
  const isStreaming = message.metadata.isStreaming ?? false;

  return (
    <div className="my-1">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-2 rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-1.5 text-left transition hover:bg-[var(--border)]"
        style={{ borderLeftColor: accentColor('thinking') }}
      >
        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Pill tone="thinking">{t('pages.tasks.thinking')}</Pill>
        {isStreaming && (
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-msg-thinking)]" />
        )}
        <span className="ml-auto text-xs text-[var(--text-tertiary)]">
          {charCount(content)} · {timestamp}
        </span>
      </button>
      {isOpen && (
        <div
          className="mt-1 w-full rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-2"
          style={{ borderLeftColor: accentColor('thinking') }}
        >
          <pre className="whitespace-pre-wrap break-words font-sans text-xs text-[var(--text-secondary)]">{content || ''}</pre>
        </div>
      )}
    </div>
  );
});
