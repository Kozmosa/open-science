import { memo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import { accentColor, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const ToolCallBlock = memo(function ToolCallBlock({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded === false);
  const content = typeof message.content === 'object' && message.content !== null
    ? (message.content as Record<string, unknown>)
    : {};
  const name = String(content.name ?? 'unknown');
  const args = content.arguments ?? content.args ?? {};

  return (
    <div className="my-1">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-2 rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-1.5 text-left transition hover:bg-[var(--border)]"
        style={{ borderLeftColor: accentColor('tool_call') }}
      >
        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Pill tone="tool-call">{t('pages.tasks.messageType.toolCall')}</Pill>
        <span className="truncate text-xs font-medium text-[var(--text-secondary)]">{name}</span>
        <span className="ml-auto shrink-0 text-xs text-[var(--text-tertiary)]">{timestamp}</span>
      </button>
      {isOpen && (
        <div
          className="mt-1 w-full rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-2"
          style={{ borderLeftColor: accentColor('tool_call') }}
        >
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(args, null, 2)}</pre>
        </div>
      )}
    </div>
  );
});
