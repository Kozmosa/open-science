import { memo } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import type { TaskSummary } from '../../types';

interface TaskNodeData extends Record<string, unknown> {
  task: TaskSummary;
}

type TaskNodeType = Node<TaskNodeData>;

function StatusDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    queued: 'bg-gray-400',
    starting: 'bg-blue-400',
    running: 'bg-green-500',
    succeeded: 'bg-emerald-500',
    failed: 'bg-red-500',
    cancelled: 'bg-amber-500',
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${colorMap[status] ?? 'bg-gray-400'}`} />;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

function TaskNode({ data, selected }: NodeProps<TaskNodeType>) {
  const { task } = data;
  return (
    <div
      className={`rounded-xl border bg-[var(--surface)] p-3 min-w-[180px] shadow-sm transition
        ${selected ? 'border-[var(--apple-blue)] ring-2 ring-[var(--apple-blue)]/20' : 'border-[var(--border)]'}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
      <div className="flex items-center gap-2 mb-1">
        <StatusDot status={task.status} />
        <span className="text-sm font-medium truncate text-[var(--text)]">{task.title}</span>
      </div>
      <div className="text-[11px] text-[var(--text-secondary)]">
        {task.environment_summary.alias} · {formatTime(task.created_at)}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
    </div>
  );
}

export default memo(TaskNode);
