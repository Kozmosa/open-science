/**
 * Performance benchmarks for markdown streaming optimizations.
 *
 * Run: cd frontend && npx vitest run __tests__/perf/markdown-streaming.perf.ts
 *
 * These benchmarks measure the raw function performance of the four
 * optimization layers. They do NOT measure React rendering (see
 * streaming-render.perf.tsx for that).
 */
import { describe, expect, it } from 'vitest';
import { marked } from 'marked';

import { mergeOutputItems, getNextOutputSeq, trimStreamingWindow } from '../../src/pages/tasks/output';
import {
  convertOutputEventsToMessages,
} from '../../src/pages/tasks/useTaskMessages';
import type { TaskOutputEvent } from '../../src/types';

// ── Helpers ──────────────────────────────────────────────────

function makeEvent(seq: number, kind: string, payload: Record<string, unknown>): TaskOutputEvent {
  return {
    task_id: 'task-1',
    seq,
    kind,
    content: JSON.stringify(payload),
    created_at: new Date().toISOString(),
  };
}

/** Generate a formula-heavy markdown string of roughly `targetChars` length. */
function generateFormulaMarkdown(targetChars: number): string {
  const block = `## Analysis

The loss function is defined as:

$$\\mathcal{L} = -\\sum_{i=1}^{n} y_i \\log(\\hat{y}_i) + (1-y_i) \\log(1-\\hat{y}_i)$$

We can simplify using the identity:

$$\\nabla_\\theta J(\\theta) = \\frac{1}{m} \\sum_{i=1}^{m} (h_\\theta(x^{(i)}) - y^{(i)}) x^{(i)}$$

For the gradient update rule: $\\theta_j := \\theta_j - \\alpha \\frac{\\partial}{\\partial \\theta_j} J(\\theta)$

The attention mechanism: $\\text{Attention}(Q, K, V) = \\text{softmax}(\\frac{QK^T}{\\sqrt{d_k}}) V$

`;
  const repeat = Math.ceil(targetChars / block.length);
  return block.repeat(repeat).slice(0, targetChars);
}

/**
 * Simulate a streaming sequence of events for a single message block.
 * `mode` controls the backend format:
 *   - 'accumulated' = old format (full text per delta, quadratic storage)
 *   - 'delta'       = new format (delta text per event, linear storage)
 */
function generateStreamingEvents(
  messageText: string,
  mode: 'accumulated' | 'delta',
  tokenSize: number = 5,
): TaskOutputEvent[] {
  const events: TaskOutputEvent[] = [];
  let seq = 0;

  // content_block_start
  seq++;
  events.push(makeEvent(seq, 'message', {
    type: 'content_block_start',
    content_block: { type: 'text', index: 0 },
    index: 0,
  }));

  // content_block_delta events
  for (let pos = 0; pos < messageText.length; pos += tokenSize) {
    seq++;
    const chunk = messageText.slice(pos, pos + tokenSize);
    const accumulated = messageText.slice(0, pos + tokenSize);

    if (mode === 'delta') {
      events.push(makeEvent(seq, 'message', {
        role: 'assistant',
        content: chunk,
        block_id: 'text-0',
        is_partial: true,
        is_delta: true,
      }));
    } else {
      events.push(makeEvent(seq, 'message', {
        role: 'assistant',
        content: accumulated,
        block_id: 'text-0',
        is_partial: true,
      }));
    }
  }

  // content_block_stop
  seq++;
  events.push(makeEvent(seq, 'message', {
    role: 'assistant',
    content: messageText,
    block_id: 'text-0',
    is_partial: false,
  }));

  return events;
}

// ── Benchmarks ───────────────────────────────────────────────

describe('Markdown Streaming Performance Benchmarks', () => {
  const sizes = [10_000, 50_000, 100_000];

  // ── 1. marked.parse raw performance ──────────────────────

  describe('marked.parse — raw throughput', () => {
    for (const size of sizes) {
      it(`${(size / 1000).toFixed(0)}K chars formula text`, () => {
        const md = generateFormulaMarkdown(size);
        const start = performance.now();
        const html = marked.parse(md, { async: false }) as string;
        const elapsed = performance.now() - start;

        console.log(`  marked.parse ${size} chars → ${elapsed.toFixed(2)} ms, output ${html.length} chars`);
        expect(html.length).toBeGreaterThan(0);
      });
    }
  });

  // ── 2. pruneSupersededDeltas ─────────────────────────────

  describe('pruneSupersededDeltas — storage reduction', () => {
    for (const size of [10_000, 50_000]) {
      it(`accumulated mode ${size} chars — prunes quadratic events`, () => {
        const events = generateStreamingEvents(generateFormulaMarkdown(size), 'accumulated');
        const start = performance.now();
        const pruned = trimStreamingWindow(events);
        const elapsed = performance.now() - start;

        const beforeBytes = events.reduce((sum, e) => sum + e.content.length, 0);
        const afterBytes = pruned.reduce((sum, e) => sum + e.content.length, 0);

        console.log(
          `  ${size} chars accumulated: ${events.length} events (${(beforeBytes / 1024).toFixed(0)} KB)` +
          ` → ${pruned.length} events (${(afterBytes / 1024).toFixed(0)} KB) in ${elapsed.toFixed(2)} ms` +
          ` — ${(afterBytes / beforeBytes * 100).toFixed(1)}% retained`
        );

        expect(pruned.length).toBeLessThan(events.length);
        expect(afterBytes).toBeLessThan(beforeBytes);
      });

      it(`delta mode ${size} chars — prunes after final event`, () => {
        const events = generateStreamingEvents(generateFormulaMarkdown(size), 'delta');
        const start = performance.now();
        const pruned = trimStreamingWindow(events);
        const elapsed = performance.now() - start;

        const beforeBytes = events.reduce((sum, e) => sum + e.content.length, 0);
        const afterBytes = pruned.reduce((sum, e) => sum + e.content.length, 0);

        console.log(
          `  ${size} chars delta: ${events.length} events (${(beforeBytes / 1024).toFixed(0)} KB)` +
          ` → ${pruned.length} events (${(afterBytes / 1024).toFixed(0)} KB) in ${elapsed.toFixed(2)} ms` +
          ` — ${(afterBytes / beforeBytes * 100).toFixed(1)}% retained`
        );

        // After final event, only the final event should remain for the block
        expect(pruned.length).toBeLessThan(events.length);
      });
    }
  });

  // ── 3. convertOutputEventsToMessages throughput ──────────

  describe('convertOutputEventsToMessages — full conversion', () => {
    for (const size of [10_000, 50_000]) {
      it(`${size} chars delta events — conversion time`, () => {
        const events = generateStreamingEvents(generateFormulaMarkdown(size), 'delta');
        const start = performance.now();
        const messages = convertOutputEventsToMessages(events, null);
        const elapsed = performance.now() - start;

        console.log(
          `  ${size} chars / ${events.length} events → ${messages.length} messages in ${elapsed.toFixed(2)} ms`
        );
        expect(messages.length).toBeGreaterThan(0);
      });

      it(`${size} chars accumulated events — conversion time`, () => {
        const events = generateStreamingEvents(generateFormulaMarkdown(size), 'accumulated');
        const start = performance.now();
        const messages = convertOutputEventsToMessages(events, null);
        const elapsed = performance.now() - start;

        console.log(
          `  ${size} chars / ${events.length} events → ${messages.length} messages in ${elapsed.toFixed(2)} ms`
        );
        expect(messages.length).toBeGreaterThan(0);
      });
    }
  });

  // ── 4. mergeOutputItems throughput ───────────────────────

  describe('mergeOutputItems — incremental merge', () => {
    it('merges 1000 events into existing 2000-event array', () => {
      const existing: TaskOutputEvent[] = Array.from({ length: 2000 }, (_, i) =>
        makeEvent(i + 1, 'message', { role: 'assistant', content: `line ${i}`, block_id: `text-${i % 5}` })
      );
      const incoming: TaskOutputEvent[] = Array.from({ length: 1000 }, (_, i) =>
        makeEvent(2001 + i, 'message', { role: 'assistant', content: `new ${i}`, block_id: `text-new-${i % 5}` })
      );

      const start = performance.now();
      const merged = mergeOutputItems(existing, incoming);
      const elapsed = performance.now() - start;

      console.log(`  merge 2000 + 1000 → ${merged.length} in ${elapsed.toFixed(2)} ms`);
      expect(merged.length).toBe(3000);
    });
  });

  // ── 5. Storage comparison: accumulated vs delta ──────────

  describe('Storage comparison — accumulated vs delta', () => {
    for (const size of [10_000, 50_000, 100_000]) {
      it(`${size} chars — total content bytes`, () => {
        const accEvents = generateStreamingEvents(generateFormulaMarkdown(size), 'accumulated');
        const deltaEvents = generateStreamingEvents(generateFormulaMarkdown(size), 'delta');

        const accBytes = accEvents.reduce((sum, e) => sum + e.content.length, 0);
        const deltaBytes = deltaEvents.reduce((sum, e) => sum + e.content.length, 0);

        console.log(
          `  ${size} chars:` +
          ` accumulated = ${(accBytes / 1024 / 1024).toFixed(2)} MB (${accEvents.length} events),` +
          ` delta = ${(deltaBytes / 1024).toFixed(1)} KB (${deltaEvents.length} events),` +
          ` ratio = ${(deltaBytes / accBytes * 100).toFixed(2)}%`
        );

        expect(deltaBytes).toBeLessThan(accBytes);
      });
    }
  });
});
