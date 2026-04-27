import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkspaceBrowserPage from './WorkspaceBrowserPage';
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
  it('renders the workspace browser page around the code-server card without another environment selector', async () => {
    renderWithProviders(<WorkspaceBrowserPage />, {
      route: '/workspace-browser',
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Workspace Browser' })).toBeInTheDocument();
    expect(screen.getByText('工作区浏览器')).toBeInTheDocument();
    expect(screen.getByTestId('code-server-card')).toBeInTheDocument();
    expect(screen.queryByTestId('environment-selector')).not.toBeInTheDocument();
  });
});
