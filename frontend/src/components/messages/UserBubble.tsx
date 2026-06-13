import { memo } from 'react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import SafeMarkdown from './SafeMarkdown';
import { accentColor, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const UserBubble = memo(function UserBubble({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-end">
      <article
        className="flex max-w-[80%] flex-col gap-1.5 rounded-xl rounded-tr-sm border-l-[3px] bg-[var(--bg-secondary)] px-3 py-2"
        style={{ borderLeftColor: accentColor('user') }}
      >
        <div className="flex items-center gap-2">
          <Pill tone="user">{t('pages.tasks.messageType.user')}</Pill>
          <span className="text-[10px] text-[var(--text-tertiary)]">{timestamp}</span>
        </div>
        <SafeMarkdown content={content} className="text-[var(--text)]" />
      </article>
    </div>
  );
});
