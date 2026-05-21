import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TokenFlowBar } from '../../../src/components/token/TokenFlowBar';

const agentSdkJson = JSON.stringify({
  total: {
    input_tokens: 48000,
    output_tokens: 8150,
    cache_creation_input_tokens: 12000,
    cache_read_input_tokens: 8500,
    cost_usd: 3.42,
  },
  by_model: {
    'claude-opus-4-7': { input_tokens: 48000, output_tokens: 8150, cost_usd: 3.42 },
  },
  source: 'agent-sdk',
});

const claudeCodeJson = JSON.stringify({
  total: { input_tokens: 39000, output_tokens: 13100 },
  source: 'claude-session-meta',
});

describe('TokenFlowBar', () => {
  it('renders token total and cost for agent-sdk source', () => {
    render(<TokenFlowBar tokenUsageJson={agentSdkJson} />);
    expect(screen.getByText(/76\.[567]\s*K/)).toBeInTheDocument();
    expect(screen.getByText(/\$3\.42/)).toBeInTheDocument();
  });

  it('renders colored segments for all token types', () => {
    const { container } = render(<TokenFlowBar tokenUsageJson={agentSdkJson} />);
    // Four segments: input, cache creation, output, cache read
    const segments = container.querySelectorAll('[title]');
    expect(segments.length).toBeGreaterThanOrEqual(3);
  });

  it('renders legend labels', () => {
    render(<TokenFlowBar tokenUsageJson={agentSdkJson} />);
    expect(screen.getByText(/Input/)).toBeInTheDocument();
    expect(screen.getByText(/Output/)).toBeInTheDocument();
  });

  it('renders without cost for claude-code source', () => {
    render(<TokenFlowBar tokenUsageJson={claudeCodeJson} />);
    expect(screen.getByText(/52\.1\s*K/)).toBeInTheDocument();
    // Should not show dollar amount
    const costElements = screen.queryByText(/\$/);
    expect(costElements).toBeNull();
  });

  it('returns null for null input', () => {
    const { container } = render(<TokenFlowBar tokenUsageJson={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('returns null for invalid JSON', () => {
    const { container } = render(<TokenFlowBar tokenUsageJson="not-json" />);
    expect(container.innerHTML).toBe('');
  });

  it('returns null for empty token data', () => {
    const empty = JSON.stringify({ total: { input_tokens: 0, output_tokens: 0 }, source: 'agent-sdk' });
    const { container } = render(<TokenFlowBar tokenUsageJson={empty} />);
    expect(container.innerHTML).toBe('');
  });
});
