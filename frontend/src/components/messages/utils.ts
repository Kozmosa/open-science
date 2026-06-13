import { useLocale } from '../../i18n';
import type { MessageItem } from '../../types';

function browserLocale(locale: 'en' | 'zh'): string {
  return locale === 'zh' ? 'zh-CN' : 'en-US';
}

export function formatTime(timestamp: string, locale: 'en' | 'zh'): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString(browserLocale(locale), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function useTimestamp(message: MessageItem): string {
  const locale = useLocale();
  return formatTime(message.metadata.timestamp, locale);
}

export function stringContent(message: MessageItem): string {
  return typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
}

export function accentColor(type: MessageItem['type']): string {
  switch (type) {
    case 'user':
      return 'var(--color-msg-user)';
    case 'assistant':
      return 'var(--color-msg-assistant)';
    case 'thinking':
      return 'var(--color-msg-thinking)';
    case 'tool_call':
      return 'var(--color-msg-tool-call)';
    case 'tool_result':
      return 'var(--color-msg-tool-result)';
    case 'system_event':
    default:
      return 'var(--color-msg-system)';
  }
}

export function firstLine(text: string, maxLength = 80): string {
  const line = text.split(/\r?\n/)[0]?.trim() ?? '';
  if (line.length <= maxLength) return line;
  return `${line.slice(0, maxLength)}…`;
}

export function charCount(text: string): string {
  const count = text.length;
  if (count < 1000) return `${count}`;
  return `${(count / 1000).toFixed(1)}k`;
}
