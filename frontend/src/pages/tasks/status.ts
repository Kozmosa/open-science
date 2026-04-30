import type { TaskStatus } from '../../types';

export const statusClassName: Record<TaskStatus, string> = {
  queued: 'border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--text-secondary)]',
  starting: 'border-[var(--apple-blue)]/20 bg-[var(--apple-blue)]/10 text-[var(--apple-blue)]',
  running: 'border-[#34c759]/20 bg-[#34c759]/10 text-[#2e7d32]',
  succeeded: 'border-[#34c759]/20 bg-[#34c759]/10 text-[#2e7d32]',
  failed: 'border-[#ff3b30]/20 bg-[#ff3b30]/10 text-[#c62828]',
};
