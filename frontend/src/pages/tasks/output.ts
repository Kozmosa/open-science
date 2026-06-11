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
 * Prune superseded streaming delta events from the output array.
 *
 * For events that carry a `block_id` (streaming message/thinking deltas),
 * only the latest event per block_id is kept. Events without a block_id
 * are always preserved.
 *
 * This converts O(N²) storage (full accumulated text per delta) into O(N)
 * at the frontend level.
 */
export function pruneSupersededDeltas(items: TaskOutputEvent[]): TaskOutputEvent[] {
  // Fast path: skip parsing if all events are non-streaming kinds
  const streamingKinds = new Set(['message', 'thinking']);
  if (!items.some((item) => streamingKinds.has(item.kind))) return items;

  // For each block_id, determine:
  //   - Whether a final (is_partial=false) event exists → prune all earlier events for that block
  //   - Whether we only have deltas (is_delta=true) → keep all (frontend appends them)
  //   - Old format (no is_delta, accumulated text) → keep only latest per block_id
  const blockFinalIdx = new Map<string, number>();   // block_id → index of final event
  const blockLatestIdx = new Map<string, number>();   // block_id → index of latest event (any kind)
  const blockHasDelta = new Map<string, boolean>();    // block_id → whether any event has is_delta
  // Set of streaming event indices that have a block_id
  const streamingWithBlockId = new Map<number, string>(); // index → block_id

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (!streamingKinds.has(item.kind)) continue;
    try {
      const payload = JSON.parse(item.content) as Record<string, unknown>;
      const blockId = payload.block_id;
      if (typeof blockId !== 'string') continue;
      streamingWithBlockId.set(i, blockId);
      blockLatestIdx.set(blockId, i);
      if (payload.is_delta === true) {
        blockHasDelta.set(blockId, true);
      }
      if (payload.is_partial === false) {
        blockFinalIdx.set(blockId, i);
      }
    } catch {
      // not JSON or no block_id — skip
    }
  }

  // If no block_ids found, nothing to prune
  if (blockLatestIdx.size === 0) return items;

  const result: TaskOutputEvent[] = [];
  for (let i = 0; i < items.length; i++) {
    // Always keep non-streaming events
    if (!streamingKinds.has(items[i].kind)) {
      result.push(items[i]);
      continue;
    }

    const blockId = streamingWithBlockId.get(i);
    if (blockId === undefined) {
      // Streaming event without block_id — keep
      result.push(items[i]);
      continue;
    }

    const finalIdx = blockFinalIdx.get(blockId);

    if (finalIdx !== undefined) {
      // Block has a final event — keep only the final event, drop all earlier ones
      if (i === finalIdx) {
        result.push(items[i]);
      }
      // else: this is an earlier event for a finalized block — prune
    } else if (blockHasDelta.get(blockId)) {
      // Block still streaming with deltas — keep all delta events (frontend appends)
      result.push(items[i]);
    } else {
      // Old format (accumulated text, no is_delta) — keep only latest
      if (i === blockLatestIdx.get(blockId)) {
        result.push(items[i]);
      }
    }
  }

  // If we didn't prune anything, return original reference for memo stability
  return result.length === items.length ? items : result;
}
