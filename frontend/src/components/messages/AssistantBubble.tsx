import { memo } from 'react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import SafeMarkdown from './SafeMarkdown';
import { accentColor, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const AssistantBubble = memo(function AssistantBubble({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-start">
      <article
        className="flex max-w-[80%] flex-col gap-1.5 rounded-xl rounded-tl-sm border-l-[3px] bg-[var(--bg-secondary)] px-3 py-2"
        style={{ borderLeftColor: accentColor('assistant') }}
      >
        <div className="flex items-center gap-2">
          <Pill tone="assistant">{t('pages.tasks.messageType.assistant')}</Pill>
          {message.metadata.isStreaming && (
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-msg-assistant)]" />
          )}
          <span className="text-[10px] text-[var(--text-tertiary)]">{timestamp}</span>
        </div>
        <SafeMarkdown content={content} className="text-[var(--text)]" />
      </article>
    </div>
  );
});
