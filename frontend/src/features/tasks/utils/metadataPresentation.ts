import type { Locale } from '@/shared/i18n/messages';

export const taskMetadataLabels: Record<Locale, Record<string, string>> = {
  en: {
    technicalDetails: 'Technical details',
    attemptId: 'Attempt ID',
    contextVersion: 'Context Version',
    contextSnapshot: 'Context Snapshot',
    runtimeSession: 'Runtime Session',
    fingerprint: 'Fingerprint',
    attemptsEmpty: 'No Attempts recorded.',
    started: 'Started',
    finished: 'Finished',
    duration: 'Duration',
    cost: 'Cost',
    runtimeSessions: 'Runtime Sessions',
    none: 'none',
    pinnedContext: 'Pinned Context',
    contextEmpty: 'No pinned Context Version.',
  },
  zh: {
    technicalDetails: '技术详情',
    attemptId: '尝试 ID',
    contextVersion: '上下文版本',
    contextSnapshot: '上下文快照',
    runtimeSession: '运行时会话',
    fingerprint: '指纹',
    attemptsEmpty: '尚未记录尝试。',
    started: '开始时间',
    finished: '结束时间',
    duration: '耗时',
    cost: '成本',
    runtimeSessions: '运行时会话',
    none: '无',
    pinnedContext: '固定上下文',
    contextEmpty: '没有固定的上下文版本。',
  },
};

export function formatTaskDateTime(
  value: string | null | undefined,
  locale: Locale,
  fallback = '—',
): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date);
}

export function shortIdentifier(value: string, visibleLength = 18): string {
  if (value.length <= visibleLength) return value;
  const edgeLength = Math.floor((visibleLength - 1) / 2);
  return `${value.slice(0, edgeLength)}…${value.slice(-edgeLength)}`;
}
