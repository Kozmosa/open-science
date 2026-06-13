import { memo } from 'react';
import { useT } from '../../i18n';
import Pill from '../shared/Pill';
import { accentColor, useTimestamp } from './utils';
import type { MessageItem } from '../../types';

export const SystemEventBlock = memo(function SystemEventBlock({ message }: { message: MessageItem }) {
  const t = useT();
  const timestamp = useTimestamp(message);
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-center px-4">
      <article
        className="flex max-w-full items-center gap-2 rounded-lg border-l-[3px] bg-[var(--bg-secondary)] px-3 py-1.5"
        style={{ borderLeftColor: accentColor('system_event') }}
      >
        <Pill tone="system" variant="outline">{t('pages.tasks.messageType.systemEvent')}</Pill>
        <span className="max-w-full break-all text-xs text-[var(--text-secondary)]">{content}</span>
        <span className="shrink-0 text-xs text-[var(--text-tertiary)]">{timestamp}</span>
      </article>
    </div>
  );
});
