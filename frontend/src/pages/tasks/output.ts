import type { TaskOutputEvent } from '../../types';

export function mergeOutputItems(
  current: TaskOutputEvent[],
  incoming: TaskOutputEvent[]
): TaskOutputEvent[] {
  const bySeq = new Map<number, TaskOutputEvent>();
  for (const item of current) {
    bySeq.set(item.seq, item);
  }
  for (const item of incoming) {
    bySeq.set(item.seq, item);
  }
  return [...bySeq.values()].sort((left, right) => left.seq - right.seq);
}

export function getNextOutputSeq(items: TaskOutputEvent[], fallback: number = 0): number {
  return items.reduce((maxSeq, item) => Math.max(maxSeq, item.seq), fallback);
}
