import { MoreHorizontal } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@design-system';
import { useT } from '@/shared/i18n';
import type { TaskSummary } from '../types';

interface TaskActionsMenuProps {
  task: TaskSummary;
  canMutate: boolean;
  disabledReason: string | null;
  interruptPending?: boolean;
  completePending?: boolean;
  reopenPending?: boolean;
  onArchive: () => void;
  onUnarchive: () => void;
  onComplete: () => void;
  onReopen: () => void;
  onInterrupt: () => void;
  onRetry: () => void;
  onMove: () => void;
  onFork: () => void;
}

const activeStatuses = new Set(['queued', 'running']);
const retryStatuses = new Set(['failed', 'cancelled']);

export default function TaskActionsMenu({
  task,
  canMutate,
  disabledReason,
  interruptPending = false,
  completePending = false,
  reopenPending = false,
  onArchive,
  onUnarchive,
  onComplete,
  onReopen,
  onInterrupt,
  onRetry,
  onMove,
  onFork,
}: TaskActionsMenuProps) {
  const t = useT();
  const disabled = !canMutate;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label="Task actions" title={disabledReason ?? undefined}>
          <MoreHorizontal size={16} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {task.archived_at ? (
          <DropdownMenuItem disabled={disabled} onSelect={onUnarchive}>Unarchive Task</DropdownMenuItem>
        ) : (
          <DropdownMenuItem disabled={disabled} onSelect={onArchive}>Archive Task</DropdownMenuItem>
        )}
        <DropdownMenuItem
          disabled={disabled || completePending || Boolean(task.archived_at) || task.work_status !== 'open'}
          onSelect={onComplete}
        >
          {t('pages.tasks.actions.complete')}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={disabled || reopenPending || Boolean(task.archived_at) || task.work_status === 'open'}
          onSelect={onReopen}
        >
          {t('pages.tasks.actions.reopen')}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={disabled || interruptPending || !activeStatuses.has(task.status)}
          onSelect={onInterrupt}
        >
          Interrupt current Turn
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={disabled || !retryStatuses.has(task.status) || Boolean(task.archived_at)}
          onSelect={onRetry}
        >
          Retry as new Turn
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled={disabled || Boolean(task.archived_at)} onSelect={onMove}>
          Move to Project…
        </DropdownMenuItem>
        <DropdownMenuItem disabled={disabled || Boolean(task.archived_at)} onSelect={onFork}>
          Fork Task…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
