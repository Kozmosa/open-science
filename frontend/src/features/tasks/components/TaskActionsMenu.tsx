import { MoreHorizontal } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@design-system';
import type { TaskSummary } from '../types';

interface TaskActionsMenuProps {
  task: TaskSummary;
  canMutate: boolean;
  disabledReason: string | null;
  interruptPending?: boolean;
  onArchive: () => void;
  onUnarchive: () => void;
  onInterrupt: () => void;
  onRetry: () => void;
  onMove: () => void;
  onFork: () => void;
}

const activeStatuses = new Set(['queued', 'starting', 'running', 'paused', 'launch_unknown']);
const retryStatuses = new Set([
  'failed',
  'cancelled',
  'stopped_by_project_archive',
  'stopped_permission_revoked',
  'stopped_runtime_unknown',
]);

export default function TaskActionsMenu({
  task,
  canMutate,
  disabledReason,
  interruptPending = false,
  onArchive,
  onUnarchive,
  onInterrupt,
  onRetry,
  onMove,
  onFork,
}: TaskActionsMenuProps) {
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
