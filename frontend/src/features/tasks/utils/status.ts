import type { TaskStatus } from '@/shared/types';
import { semanticToneClasses } from '@design-system';
import type { MessageKey } from '@/shared/i18n/messages';

type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

export const statusClassName: Record<TaskStatus, string> = {
  queued: semanticToneClasses.muted,
  starting: semanticToneClasses.info,
  running: semanticToneClasses.success,
  succeeded: semanticToneClasses.success,
  failed: semanticToneClasses.danger,
  cancelled: semanticToneClasses.warning,
  paused: semanticToneClasses.info,
  launch_unknown: semanticToneClasses.warning,
  stopped_by_project_archive: semanticToneClasses.muted,
  stopped_permission_revoked: semanticToneClasses.danger,
  stopped_runtime_unknown: semanticToneClasses.warning,
};

const statusMessageKey: Record<TaskStatus, MessageKey> = {
  queued: 'pages.tasks.status.queued',
  starting: 'pages.tasks.status.starting',
  running: 'pages.tasks.status.running',
  succeeded: 'pages.tasks.status.succeeded',
  failed: 'pages.tasks.status.failed',
  cancelled: 'pages.tasks.status.cancelled',
  paused: 'pages.tasks.status.paused',
  launch_unknown: 'pages.tasks.status.launch_unknown',
  stopped_by_project_archive: 'pages.tasks.status.stopped_by_project_archive',
  stopped_permission_revoked: 'pages.tasks.status.stopped_permission_revoked',
  stopped_runtime_unknown: 'pages.tasks.status.stopped_runtime_unknown',
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
