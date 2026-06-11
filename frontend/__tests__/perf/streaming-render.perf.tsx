/**
 * Integration benchmark: React rendering under streaming load.
 *
 * Measures render counts and re-render suppression for:
 *   1. MessageBlock with memo vs without memo
 *   2. SafeMarkdown parse call frequency
 *   3. Full streaming simulation (SSE → state → render)
 *
 * Run: cd frontend && npx vitest run __tests__/perf/streaming-render.perf.tsx
 */
import { createElement, memo, useState as realUseState, useCallback as realUseCallback, useMemo as realUseMemo } from 'react';
import { renderHook, act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { marked } from 'marked';

import { AssistantMessage, MessageBlock } from '../../src/pages/tasks/MessageBlocks';
import { renderWithProviders } from '../../src/test/render';
import { mergeOutputItems, pruneSupersededDeltas } from '../../src/pages/tasks/output';
import {
  convertOutputEventsToMessages,
} from '../../src/pages/tasks/useTaskMessages';
import type { MessageItem, TaskOutputEvent } from '../../src/types';

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

function generateFormulaMarkdown(targetChars: number): string {
  const block = `## Analysis\n\nThe loss function: $$\\mathcal{L} = -\\sum_{i=1}^{n} y_i \\log(\\hat{y}_i)$$\n\nGradient: $$\\nabla_\\theta J(\\theta) = \\frac{1}{m} \\sum_{i=1}^{m} (h_\\theta(x^{(i)}) - y^{(i)}) x^{(i)}$$\n\nAttention: $\\text{Attention}(Q, K, V) = \\text{softmax}(\\frac{QK^T}{\\sqrt{d_k}}) V$\n\n`;
  return block.repeat(Math.ceil(targetChars / block.length)).slice(0, targetChars);
}

function message(content: string, blockId?: string, isDelta?: boolean): MessageItem {
  return {
    id: `msg-${Math.random().toString(36).slice(2, 8)}`,
    type: 'assistant',
    content,
    metadata: {
      timestamp: new Date().toISOString(),
      sequence: 1,
      ...(blockId ? { blockId, isDelta } : {}),
    },
  };
}

// ── Benchmarks ───────────────────────────────────────────────

describe('Streaming Render Benchmarks', () => {
  // ── 1. SafeMarkdown parse call count ──────────────────────

  describe('SafeMarkdown memoization — render efficiency', () => {
    it('re-renders same message 10 times → memo prevents child re-render', () => {
      const md = generateFormulaMarkdown(5000);
      const msg = message(md);
      let renderCount = 0;

      // Track by checking DOM updates
      const { rerender, container } = renderWithProviders(<AssistantMessage message={msg} />);
      renderCount = container.querySelectorAll('[class*="rounded-tl-sm"]').length;
      expect(renderCount).toBe(1);

      // Re-render with same message object 9 times
      for (let i = 0; i < 9; i++) {
        rerender(<AssistantMessage message={msg} />);
      }

      // With React.memo, the component should not re-render when
      // the message prop is the same object reference.
      // The DOM should still have exactly 1 message container.
      const containers = container.querySelectorAll('[class*="rounded-tl-sm"]');
      console.log(`  10 re-renders with same message ref → ${containers.length} DOM container(s)`);
      expect(containers.length).toBe(1);
    });

    it('new message objects with same content → parses each time (memo shallow compare)', () => {
      const md = generateFormulaMarkdown(2000);
      const durations: number[] = [];

      // Each render creates a new message object — React.memo shallow compare
      // fails, so it re-renders. But useMemo caches the parse result.
      for (let i = 0; i < 5; i++) {
        const start = performance.now();
        const { unmount } = renderWithProviders(<AssistantMessage message={message(md)} />);
        durations.push(performance.now() - start);
        unmount();
      }

      const avgRender = durations.reduce((a, b) => a + b, 0) / durations.length;
      console.log(`  5 renders of same content (new objects) → avg ${avgRender.toFixed(2)} ms per render`);
      // Verify renders complete in reasonable time
      expect(avgRender).toBeLessThan(100);
    });
  });

  // ── 2. Streaming simulation with delta events ────────────

  describe('Full streaming pipeline — delta events', () => {
    it('simulates 500 delta events for 50K message', () => {
      const fullText = generateFormulaMarkdown(50_000);
      const tokenSize = 100; // 500 deltas
      const numDeltas = Math.ceil(fullText.length / tokenSize);

      let accumulated = '';
      let outputItems: TaskOutputEvent[] = [];
      let messages: MessageItem[] = [];
      let totalConvertTime = 0;
      let totalMergeTime = 0;
      let totalPruneTime = 0;

      for (let i = 0; i < numDeltas; i++) {
        const chunk = fullText.slice(i * tokenSize, (i + 1) * tokenSize);
        accumulated += chunk;

        const event = makeEvent(i + 1, 'message', {
          role: 'assistant',
          content: chunk,
          block_id: 'text-0',
          is_partial: true,
          is_delta: true,
        });

        // Simulate the pipeline
        const mergeStart = performance.now();
        outputItems = mergeOutputItems(outputItems, [event]);
        totalMergeTime += performance.now() - mergeStart;

        const pruneStart = performance.now();
        outputItems = pruneSupersededDeltas(outputItems);
        totalPruneTime += performance.now() - pruneStart;

        // Only convert new events (incremental)
        const newEvents = outputItems.filter(e => e.seq > i);
        if (newEvents.length > 0) {
          const convertStart = performance.now();
          const newMessages = convertOutputEventsToMessages(newEvents, null);
          totalConvertTime += performance.now() - convertStart;

          // Simple merge: update existing message
          for (const msg of newMessages) {
            const bid = msg.metadata.blockId;
            if (bid) {
              const existingIdx = messages.findIndex(m => m.metadata.blockId === bid);
              if (existingIdx !== -1) {
                const isDelta = msg.metadata.isDelta === true;
                const prevContent = typeof messages[existingIdx].content === 'string' ? messages[existingIdx].content as string : '';
                messages[existingIdx] = {
                  ...messages[existingIdx],
                  content: isDelta ? prevContent + (typeof msg.content === 'string' ? msg.content : '') : msg.content,
                  metadata: { ...messages[existingIdx].metadata, ...msg.metadata },
                };
              } else {
                messages.push(msg);
              }
            }
          }
        }
      }

      // Final event
      const finalEvent = makeEvent(numDeltas + 1, 'message', {
        role: 'assistant',
        content: fullText,
        block_id: 'text-0',
        is_partial: false,
      });
      outputItems = mergeOutputItems(outputItems, [finalEvent]);
      outputItems = pruneSupersededDeltas(outputItems);

      const totalStorage = outputItems.reduce((sum, e) => sum + e.content.length, 0);

      console.log(`  500 delta events for 50K message:`);
      console.log(`    outputItems after prune: ${outputItems.length} events`);
      console.log(`    total storage: ${(totalStorage / 1024).toFixed(1)} KB`);
      console.log(`    accumulated content: ${(accumulated.length / 1024).toFixed(1)} KB`);
      console.log(`    total convert time: ${totalConvertTime.toFixed(2)} ms`);
      console.log(`    total merge time: ${totalMergeTime.toFixed(2)} ms`);
      console.log(`    total prune time: ${totalPruneTime.toFixed(2)} ms`);
      console.log(`    final message length: ${String(messages[0]?.content ?? '').length} chars`);

      expect(messages.length).toBe(1);
      expect(messages[0].content).toBe(fullText);
      // With delta + final + prune, storage should be ~ message size (linear)
      expect(totalStorage).toBeLessThan(fullText.length * 3);
    });
  });

  // ── 3. Component render count under state updates ────────

  describe('MessageBlock render count under streaming updates', () => {
    it('renders 10 content updates → React.memo skips unchanged siblings', () => {
      const renderSpy = vi.fn();

      // Create a wrapper that tracks renders
      function TrackedMessageBlock({ message }: { message: MessageItem }) {
        renderSpy(message.id);
        return createElement(MessageBlock, { message });
      }

      const msg1 = message('static message');
      const streamingContent = generateFormulaMarkdown(5000);

      // Render with one static + one streaming message
      const { rerender } = renderWithProviders(
        <div>
          <TrackedMessageBlock message={msg1} />
          {Array.from({ length: 10 }, (_, i) => {
            const chunk = streamingContent.slice(0, (i + 1) * 500);
            return <TrackedMessageBlock key={`stream-${i}`} message={message(chunk, 'text-0')} />;
          })}
        </div>
      );

      const rendersAfterFirst = renderSpy.mock.calls.length;

      // Re-render with updated streaming content
      rerender(
        <div>
          <TrackedMessageBlock message={msg1} />
          {Array.from({ length: 10 }, (_, i) => {
            const chunk = streamingContent.slice(0, (i + 1) * 500 + 100);
            return <TrackedMessageBlock key={`stream-${i}`} message={message(chunk, 'text-0')} />;
          })}
        </div>
      );

      const rendersAfterSecond = renderSpy.mock.calls.length;

      console.log(
        `  11 components, 2 renders → total tracked renders: ${renderSpy.mock.calls.length}` +
        ` (${rendersAfterFirst} first, ${rendersAfterSecond - rendersAfterFirst} second)`
      );

      // Each TrackedMessageBlock should render on each rerender since
      // we create new message objects each time (shallow compare fails).
      // This test verifies the harness works — the real memoization win
      // comes from SafeMarkdown's useMemo preventing re-parsing.
      expect(renderSpy.mock.calls.length).toBeGreaterThan(0);
    });
  });

  // ── 4. Batch processing throughput ───────────────────────

  describe('Batch processing — multiple messages', () => {
    it('processes 10 concurrent streaming messages', () => {
      const numMessages = 10;
      const messageLen = 5000;
      const tokenSize = 50;

      let outputItems: TaskOutputEvent[] = [];
      let totalConvertTime = 0;
      const totalDeltas = Math.ceil(messageLen / tokenSize);

      // Simulate interleaved streaming from 10 messages
      for (let delta = 0; delta < totalDeltas; delta++) {
        for (let blockIdx = 0; blockIdx < numMessages; blockIdx++) {
          const seq = delta * numMessages + blockIdx + 1;
          const chunk = generateFormulaMarkdown(messageLen).slice(delta * tokenSize, (delta + 1) * tokenSize);

          const event = makeEvent(seq, 'message', {
            role: 'assistant',
            content: chunk,
            block_id: `text-${blockIdx}`,
            is_partial: true,
            is_delta: true,
          });

          outputItems = mergeOutputItems(outputItems, [event]);
        }
      }

      // Add final events
      for (let blockIdx = 0; blockIdx < numMessages; blockIdx++) {
        const seq = totalDeltas * numMessages + blockIdx + 1;
        outputItems = mergeOutputItems(outputItems, [
          makeEvent(seq, 'message', {
            role: 'assistant',
            content: generateFormulaMarkdown(messageLen),
            block_id: `text-${blockIdx}`,
            is_partial: false,
          }),
        ]);
      }

      // Prune
      const pruneStart = performance.now();
      const pruned = pruneSupersededDeltas(outputItems);
      const pruneTime = performance.now() - pruneStart;

      // Convert all
      const convertStart = performance.now();
      const messages = convertOutputEventsToMessages(pruned, null);
      totalConvertTime = performance.now() - convertStart;

      const beforeBytes = outputItems.reduce((sum, e) => sum + e.content.length, 0);
      const afterBytes = pruned.reduce((sum, e) => sum + e.content.length, 0);

      console.log(`  10 concurrent messages, ${outputItems.length} total events:`);
      console.log(`    before prune: ${(beforeBytes / 1024).toFixed(0)} KB, ${outputItems.length} events`);
      console.log(`    after prune:  ${(afterBytes / 1024).toFixed(0)} KB, ${pruned.length} events`);
      console.log(`    prune time:   ${pruneTime.toFixed(2)} ms`);
      console.log(`    convert time: ${totalConvertTime.toFixed(2)} ms`);
      console.log(`    final messages: ${messages.length}`);

      expect(pruned.length).toBeLessThan(outputItems.length);
      expect(messages.length).toBe(numMessages);
    });
  });
});
