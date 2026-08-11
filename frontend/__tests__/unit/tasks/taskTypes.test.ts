import { describe, expect, it } from 'vitest';
import {
  parseForkEngineFamily,
  parseForkHarnessEngine,
  parseForkTransferMode,
} from '@features/tasks/types';

describe('fork transport enum parsers', () => {
  it('accepts only generated engine families', () => {
    expect(parseForkEngineFamily('codex')).toBe('codex');
    expect(parseForkEngineFamily('claude')).toBe('claude');
    expect(parseForkEngineFamily('unknown')).toBeNull();
  });

  it('accepts only generated harness engines', () => {
    expect(parseForkHarnessEngine('codex-app-server')).toBe('codex-app-server');
    expect(parseForkHarnessEngine('agent-sdk')).toBe('agent-sdk');
    expect(parseForkHarnessEngine('claude-code')).toBe('claude-code');
    expect(parseForkHarnessEngine('unknown')).toBeNull();
  });

  it('accepts only generated transfer modes', () => {
    expect(parseForkTransferMode('selected_turns')).toBe('selected_turns');
    expect(parseForkTransferMode('recent_turns')).toBe('recent_turns');
    expect(parseForkTransferMode('full_transcript')).toBe('full_transcript');
    expect(parseForkTransferMode('context_only')).toBe('context_only');
    expect(parseForkTransferMode('unknown')).toBeNull();
  });
});
