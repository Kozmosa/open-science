import { MoreHorizontal } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@design-system';
import type { TaskRecord } from '@/shared/types';

interface TaskActionsMenuProps {
  task: TaskRecord;
  canMutate: boolean;
  disabledReason: string | null;
  onArchive: () => void;
  onUnarchive: () => void;
  onCancel: () => void;
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
  onArchive,
  onUnarchive,
  onCancel,
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
          disabled={disabled || !activeStatuses.has(task.status)}
          onSelect={onCancel}
        >
          Cancel current Attempt
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={disabled || !retryStatuses.has(task.status) || Boolean(task.archived_at)}
          onSelect={onRetry}
        >
          Retry as new Attempt
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
