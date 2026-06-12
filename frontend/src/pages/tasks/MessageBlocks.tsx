import { marked } from 'marked';
import { memo, useEffect, useRef, useState } from 'react';
import { useLocale, useT } from '../../i18n';
import type { MessageItem } from '../../types';

function browserLocale(locale: 'en' | 'zh'): string {
  return locale === 'zh' ? 'zh-CN' : 'en-US';
}

function formatTime(timestamp: string, locale: 'en' | 'zh'): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString(browserLocale(locale), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function messageTypeLabel(type: string, t: ReturnType<typeof useT>): string {
  switch (type) {
    case 'system_event':
      return t('pages.tasks.messageType.systemEvent');
    case 'user':
      return t('pages.tasks.messageType.user');
    case 'assistant':
      return t('pages.tasks.messageType.assistant');
    case 'thinking':
      return t('pages.tasks.messageType.thinking');
    case 'tool_call':
      return t('pages.tasks.messageType.toolCall');
    case 'tool_result':
      return t('pages.tasks.messageType.toolResult');
    case 'stdout':
      return t('pages.tasks.messageType.stdout');
    case 'stderr':
      return t('pages.tasks.messageType.stderr');
    case 'lifecycle':
      return t('pages.tasks.messageType.lifecycle');
    default:
      return type.replace('_', ' ');
  }
}

const PROSE_STYLES = 'prose-sm [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_code]:rounded [&_code]:bg-[var(--bg-tertiary)] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_pre]:my-1 [&_pre]:rounded-lg [&_pre]:bg-[var(--bg-tertiary)] [&_pre]:p-2 [&_blockquote]:my-1 [&_blockquote]:border-l-2 [&_blockquote]:border-[var(--text-tertiary)] [&_blockquote]:pl-3 [&_blockquote]:text-[var(--text-secondary)] [&_a]:text-[var(--apple-blue)] [&_a]:underline [&_strong]:font-semibold [&_em]:italic [&_hr]:my-2 [&_hr]:border-[var(--border)] [&_table]:my-1 [&_table]:w-full [&_th]:border [&_th]:border-[var(--border)] [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-[var(--border)] [&_td]:px-2 [&_td]:py-1';

const SafeMarkdown = memo(function SafeMarkdown({ content, className }: { content: string; className?: string }) {
  // Debounce markdown parsing: during streaming, deltas arrive every ~5ms.
  // Parsing on every delta is wasteful — batch them with a short delay.
  const [parsedHtml, setParsedHtml] = useState(() => marked.parse(content, { async: false }) as string);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contentRef = useRef(content);
  contentRef.current = content;

  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setParsedHtml(marked.parse(contentRef.current, { async: false }) as string);
    }, 80);
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, [content]);

  return (
    <div
      className={`break-words font-sans text-sm [&_p]:whitespace-pre-wrap ${PROSE_STYLES} ${className ?? ''}`}
      dangerouslySetInnerHTML={{ __html: parsedHtml }}
    />
  );
});

export const SystemEventBlock = memo(function SystemEventBlock({ message }: { message: MessageItem }) {
  const locale = useLocale();
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-center px-4">
      <div className="flex max-w-full items-center gap-2 rounded-lg border-l-2 border-[var(--info)] bg-[var(--bg-secondary)] px-3 py-1.5">
        <span className="max-w-full break-all text-xs text-[var(--text-secondary)]">{content}</span>
        <span className="shrink-0 text-xs text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp, locale)}</span>
      </div>
    </div>
  );
});

export const UserMessage = memo(function UserMessage({ message }: { message: MessageItem }) {
  const locale = useLocale();
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm border border-[var(--info-border)] bg-[var(--info-soft)] px-4 py-2">
        <SafeMarkdown content={content} className="text-[var(--info-foreground)]" />
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp, locale)}</div>
      </div>
    </div>
  );
});

export const AssistantMessage = memo(function AssistantMessage({ message }: { message: MessageItem }) {
  const locale = useLocale();
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] px-4 py-2">
        <SafeMarkdown content={content} className="text-[var(--text)]" />
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp, locale)}</div>
      </div>
    </div>
  );
});

export const ThinkingBlock = memo(function ThinkingBlock({ message }: { message: MessageItem }) {
  const isStreaming = message.metadata.isStreaming ?? false;
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded !== true);
  const t = useT();
  const content = typeof message.content === 'string' ? message.content : '';
  return (
    <div className="my-1 flex flex-col items-start">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex items-center gap-1 rounded-lg border-l-2 border-[var(--text-tertiary)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
      >
        {isOpen ? '▾' : '▸'} {t('pages.tasks.thinking')}
        {isStreaming && <span className="ml-1 inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--apple-blue)]" />}
      </button>
      {isOpen && (
        <div className="mt-1 w-full rounded-lg border-l-2 border-[var(--text-tertiary)] bg-[var(--bg-secondary)] px-3 py-2">
          <pre className="whitespace-pre-wrap break-words font-sans text-xs text-[var(--text-secondary)]">{content || ''}</pre>
        </div>
      )}
    </div>
  );
});

export const ToolCallBlock = memo(function ToolCallBlock({ message }: { message: MessageItem }) {
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded !== true);
  const t = useT();
  const content = typeof message.content === 'object' ? message.content : {};
  const name = String((content as Record<string, unknown>).name || 'unknown');
  return (
    <div className="my-1 flex flex-col items-start">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex items-center gap-1 rounded-lg border-l-2 border-[var(--info)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
      >
        {isOpen ? '▾' : '▸'} {t('pages.tasks.toolCall', { name })}
      </button>
      {isOpen && (
        <div className="mt-1 w-full rounded-lg border-l-2 border-[var(--info)] bg-[var(--bg-secondary)] px-3 py-2">
          <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(content, null, 2)}</pre>
        </div>
      )}
    </div>
  );
});

export const ToolResultBlock = memo(function ToolResultBlock({ message }: { message: MessageItem }) {
  const [isOpen, setIsOpen] = useState(message.metadata.isFolded !== true);
  const t = useT();
  const content = typeof message.content === 'object' ? message.content : String(message.content ?? '');
  return (
    <div className="my-1 flex flex-col items-start pl-4">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="flex items-center gap-1 rounded-lg border-l-2 border-[var(--success)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
      >
        {isOpen ? '▾' : '▸'} {t('pages.tasks.toolResult')}
      </button>
      {isOpen && (
        <div className="mt-1 w-full rounded-lg border-l-2 border-[var(--success)] bg-[var(--bg-secondary)] px-3 py-2">
          {typeof content === 'string' ? (
            <SafeMarkdown content={content} className="text-xs text-[var(--text-secondary)]" />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(content, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
});

interface CollapsedGroupItem {
  id: string;
  messages: MessageItem[];
  collapsed: boolean;
}

export function CollapsedGroupBlock({ item, onToggle }: { item: CollapsedGroupItem; onToggle: () => void }) {
  const t = useT();

  if (!item.collapsed) {
    return (
      <div className="space-y-1">
        {item.messages.map(msg => (
          <MessageBlock key={msg.id} message={msg} />
        ))}
      </div>
    );
  }

  const counts = item.messages.reduce((acc, msg) => {
    acc[msg.type] = (acc[msg.type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const summary = Object.entries(counts)
    .map(([type, count]) => t('pages.tasks.messageGroup.summary', { count, type: messageTypeLabel(type, t) }))
    .join(', ');

  return (
    <div className="my-2 flex justify-center">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={false}
        className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition hover:bg-[var(--border)]"
      >
        <span>▸ {summary}</span>
        <span className="text-[var(--text-tertiary)]">({item.messages.length})</span>
      </button>
    </div>
  );
}

export const MessageBlock = memo(function MessageBlock({ message }: { message: MessageItem }) {
  switch (message.type) {
    case 'system_event':
      return <SystemEventBlock message={message} />;
    case 'user':
      return <UserMessage message={message} />;
    case 'assistant':
      return <AssistantMessage message={message} />;
    case 'thinking':
      return <ThinkingBlock message={message} />;
    case 'tool_call':
      return <ToolCallBlock message={message} />;
    case 'tool_result':
      return <ToolResultBlock message={message} />;
    default:
      return <AssistantMessage message={message} />;
  }
});
