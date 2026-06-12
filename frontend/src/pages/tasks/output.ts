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

/**
 * Trim streaming delta events to a sliding window per block_id.
 *
 * For each block_id, only the most recent `windowSize` deltas are kept.
 * Final events (is_partial=false) are always kept.
 * Events without a block_id are always kept.
 *
 * This prevents `outputItems` from growing unboundedly during long
 * streaming responses while still providing enough recent deltas for
 * SSE reconnection replay.
 */
const STREAMING_WINDOW = 50;

/** Hard cap on how many output events are rendered at once. The rendered stream
 *  keeps only the most recent events so the DOM cannot grow unboundedly during
 *  long runs; older history stays reachable via scroll-up loadMore (served from
 *  the backend, which is the source of truth). */
const MAX_RENDER_ITEMS = 200;

function capRenderWindow(items: TaskOutputEvent[]): TaskOutputEvent[] {
  return items.length > MAX_RENDER_ITEMS ? items.slice(items.length - MAX_RENDER_ITEMS) : items;
}

export function trimStreamingWindow(items: TaskOutputEvent[], windowSize: number = STREAMING_WINDOW): TaskOutputEvent[] {
  const streamingKinds = new Set(['message', 'thinking']);
  if (!items.some((item) => streamingKinds.has(item.kind))) return capRenderWindow(items);

  // Collect indices per block_id for streaming events
  const blockIndices = new Map<string, number[]>();  // block_id → [indices]
  const finalIndices = new Set<number>();              // indices of final events
  const streamingByIndex = new Map<number, string>();  // index → block_id

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (!streamingKinds.has(item.kind)) continue;
    try {
      const payload = JSON.parse(item.content) as Record<string, unknown>;
      const blockId = payload.block_id;
      if (typeof blockId !== 'string') continue;
      streamingByIndex.set(i, blockId);
      if (payload.is_partial === false) {
        finalIndices.add(i);
      } else {
        let indices = blockIndices.get(blockId);
        if (!indices) {
          indices = [];
          blockIndices.set(blockId, indices);
        }
        indices.push(i);
      }
    } catch {
      // not JSON or no block_id — skip
    }
  }

  if (streamingByIndex.size === 0) return capRenderWindow(items);

  // For each block, mark the oldest deltas beyond the window for removal
  const removeIndices = new Set<number>();
  for (const indices of blockIndices.values()) {
    if (indices.length <= windowSize) continue;
    const cutoff = indices.length - windowSize;
    for (let j = 0; j < cutoff; j++) {
      removeIndices.add(indices[j]);
    }
  }

  if (removeIndices.size === 0) return capRenderWindow(items);

  const result: TaskOutputEvent[] = [];
  for (let i = 0; i < items.length; i++) {
    if (!removeIndices.has(i)) {
      result.push(items[i]);
    }
  }
  return capRenderWindow(result);
}
