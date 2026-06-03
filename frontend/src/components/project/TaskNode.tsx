import { memo } from 'react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import { semanticDotClasses } from '../ui/theme';
import { useLocale } from '../../i18n';
import type { TaskSummary } from '../../types';

interface TaskNodeData extends Record<string, unknown> {
  task: TaskSummary;
}

type TaskNodeType = Node<TaskNodeData>;

function StatusDot({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    queued: semanticDotClasses.muted,
    starting: semanticDotClasses.info,
    running: semanticDotClasses.success,
    succeeded: semanticDotClasses.success,
    failed: semanticDotClasses.danger,
    cancelled: semanticDotClasses.warning,
    paused: semanticDotClasses.info,
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${colorMap[status] ?? semanticDotClasses.muted}`} />;
}

function formatTime(iso: string, locale: 'en' | 'zh'): string {
  return new Date(iso).toLocaleDateString(locale === 'zh' ? 'zh-CN' : 'en-US');
}

function TaskNode({ data, selected }: NodeProps<TaskNodeType>) {
  const { task } = data;
  const locale = useLocale();
  return (
    <div
      className={`rounded-xl border bg-[var(--surface)] p-3 min-w-[180px] shadow-sm transition
        ${selected ? 'border-[var(--apple-blue)] ring-2 ring-[var(--apple-blue)]/20' : 'border-[var(--border)]'}`}
    >
      <Handle id="target" type="target" position={Position.Left} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
      <div className="flex items-center gap-2 mb-1">
        <StatusDot status={task.status} />
        <span className="truncate text-sm font-medium text-[var(--text)]" title={task.title}>{task.title}</span>
      </div>
      <div className="text-[11px] text-[var(--text-secondary)]">
        {task.environment_summary?.alias ?? task.environment_id} · {formatTime(task.created_at, locale)}
      </div>
      <Handle id="source" type="source" position={Position.Right} className="!bg-[var(--apple-blue)] !w-2 !h-2" />
    </div>
  );
}

export default memo(TaskNode);
