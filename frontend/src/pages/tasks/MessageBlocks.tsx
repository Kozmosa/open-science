import { useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useLocale, useT } from '../../i18n';
import { workspaceFileBrowserHref } from '../../utils/workspaceFileLinks';
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

const markdownLinkPattern = /\[([^\]]+)\]\(([^)]+)\)/g;

function RenderedMessageText({ content, className }: { content: string; className: string }) {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  for (const match of content.matchAll(markdownLinkPattern)) {
    const [fullMatch, label, target] = match;
    const index = match.index ?? 0;
    if (index > lastIndex) {
      nodes.push(content.slice(lastIndex, index));
    }
    const workspaceHref = workspaceFileBrowserHref(target);
    if (workspaceHref) {
      nodes.push(
        <Link
          key={`${target}-${index}`}
          to={workspaceHref}
          className="underline decoration-[var(--apple-blue)] underline-offset-2 hover:text-[var(--apple-blue)]"
        >
          {label}
        </Link>
      );
    } else {
      nodes.push(fullMatch);
    }
    lastIndex = index + fullMatch.length;
  }
  if (lastIndex < content.length) {
    nodes.push(content.slice(lastIndex));
  }
  return <pre className={className}>{nodes}</pre>;
}

export function SystemEventBlock({ message }: { message: MessageItem }) {
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
}

export function UserMessage({ message }: { message: MessageItem }) {
  const locale = useLocale();
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm border border-[var(--info-border)] bg-[var(--info-soft)] px-4 py-2">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--info-foreground)]">{content}</pre>
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp, locale)}</div>
      </div>
    </div>
  );
}

export function AssistantMessage({ message }: { message: MessageItem }) {
  const locale = useLocale();
  const content = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
  return (
    <div className="my-2 flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] px-4 py-2">
        <RenderedMessageText content={content} className="whitespace-pre-wrap break-words font-sans text-sm text-[var(--text)]" />
        <div className="mt-1 text-right text-[10px] text-[var(--text-tertiary)]">{formatTime(message.metadata.timestamp, locale)}</div>
      </div>
    </div>
  );
}

export function ThinkingBlock({ message }: { message: MessageItem }) {
  const isStreaming = message.metadata.isStreaming ?? false;
  const [isOpen, setIsOpen] = useState(isStreaming || message.metadata.isFolded !== true);
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
}

export function ToolCallBlock({ message }: { message: MessageItem }) {
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
}

export function ToolResultBlock({ message }: { message: MessageItem }) {
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
            <RenderedMessageText content={content} className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]" />
          ) : (
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--text-secondary)]">{JSON.stringify(content, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}

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

export function MessageBlock({ message }: { message: MessageItem }) {
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
}
