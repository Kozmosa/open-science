import { QueryClient } from '@tanstack/react-query';
import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkspaceBrowserPage from './WorkspaceBrowserPage';
import { createTestQueryClient, renderWithProviders } from '../test/render';
import type { EnvironmentRecord, SystemHealth } from '../types';

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
  CodeServerCard: () => <div data-testid="code-server-card" />,
  EnvironmentSelectorPanel: () => <div data-testid="environment-selector" />,
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

describe('WorkspaceBrowserPage', () => {
  it('shows runtime readiness blockers before the workspace browser is opened', async () => {
    const client: QueryClient = createTestQueryClient();
    const health: SystemHealth = {
      status: 'ok',
      state_root: '.ainrf',
      startup_cwd: '/repo',
      default_workspace_dir: '/repo/workspace/default',
      container_configured: false,
      container_health: null,
      runtime_readiness: {
        ready: false,
        dependencies: {
          tmux: {
            available: false,
            path: null,
            detail: 'Install tmux to use localhost terminals and workspace browser.',
          },
          uv: { available: true, path: '/usr/bin/uv', detail: null },
          code_server: {
            available: false,
            path: null,
            detail: 'Install code-server from Settings before using the workspace browser.',
          },
        },
      },
      detail: null,
    };
    client.setQueryData(['health'], health);

    renderWithProviders(<WorkspaceBrowserPage />, {
      route: '/workspace-browser',
      locale: 'en',
      client,
    });

    expect(await screen.findByText('Runtime setup required')).toBeInTheDocument();
    expect(screen.getByText('Install tmux to use localhost terminals and workspace browser.')).toBeInTheDocument();
    expect(screen.getByText('Install code-server from Settings before using the workspace browser.')).toBeInTheDocument();
  });
});
