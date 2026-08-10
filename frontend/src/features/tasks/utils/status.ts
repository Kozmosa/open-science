import type { TaskStatus } from '../types';
import { semanticToneClasses } from '@design-system';
import type { MessageKey } from '@/shared/i18n/messages';

type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

export const statusClassName: Record<TaskStatus, string> = {
  queued: semanticToneClasses.muted,
  running: semanticToneClasses.success,
  succeeded: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  cancelled: semanticToneClasses.warning,
  completed: semanticToneClasses.muted,
};

const statusMessageKey: Record<TaskStatus, MessageKey> = {
  queued: 'pages.tasks.status.queued',
  running: 'pages.tasks.status.running',
  succeeded: 'pages.tasks.status.succeeded',
  failed: 'pages.tasks.status.failed',
  cancelled: 'pages.tasks.status.cancelled',
  completed: 'pages.tasks.status.completed',
};

function isTaskStatus(status: string): status is TaskStatus {
  return Object.hasOwn(statusClassName, status);
}

function humanizeStatus(status: string): string {
  const normalized = status.trim().replace(/[-_]+/g, ' ');
  if (!normalized) return 'Unknown';
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function taskStatusClassName(status: string): string {
  return isTaskStatus(status) ? statusClassName[status] : semanticToneClasses.warning;
}

export function taskStatusLabel(t: Translate, status: string): string {
  return isTaskStatus(status) ? t(statusMessageKey[status]) : humanizeStatus(status);
}
