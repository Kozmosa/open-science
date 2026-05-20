import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TerminalPage from './TerminalPage';
import { renderWithProviders } from '../test/render';
import type { EnvironmentRecord } from '../types';

const selectedEnvironment: EnvironmentRecord = {
  id: 'env-1',
  alias: 'gpu-lab',
  display_name: 'GPU Lab',
  description: null,
  is_seed: false,
  tags: [],
  host: 'gpu.example.com',
  port: 22,
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: null,
  proxy_jump: null,
  proxy_command: null,
  ssh_options: {},
  default_workdir: '/workspace/project',
  preferred_python: null,
  preferred_env_manager: null,
  preferred_runtime_notes: null,
  task_harness_profile: 'Use the configured GPU environment.',
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:00:00Z',
  code_server_path: null,
  latest_detection: null,
};

vi.mock('../components', () => ({
  TerminalBenchCard: () => <div data-testid="terminal-bench-card" />,
  useEnvironmentSelection: () => ({
    selectedEnvironment,
    selectedEnvironmentId: selectedEnvironment.id,
    selectedReference: null,
    isLoading: false,
    loadError: null,
    environments: [selectedEnvironment],
    onSelectEnvironment: vi.fn(),
  }),
}));

beforeEach(() => {
  window.localStorage.clear();
});

describe('TerminalPage', () => {
  it('renders the terminal bench card as the sole page content', () => {
    renderWithProviders(<TerminalPage />, {
      route: '/terminal',
      locale: 'en',
    });

    expect(screen.getByTestId('terminal-bench-card')).toBeInTheDocument();
  });

  it('does not expose task-attach intent labels in the terminal page content', async () => {
    renderWithProviders(<TerminalPage />, {
      route: '/terminal?environment_id=env-1&task_id=task-1&intent=takeover',
      locale: 'zh',
    });

    expect(await screen.findByTestId('terminal-bench-card')).toBeInTheDocument();
    expect(screen.queryByTestId('environment-selector')).not.toBeInTheDocument();
  });
});
