import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getEnvironments, getProjectEnvironmentReferences } from '../../api';
import { renderWithProviders } from '../../test/render';
import type { EnvironmentRecord } from '../../types';
import { createDefaultWebUiSettings, settingsStorageKey } from '../../settings';
import EnvironmentSelectorPanel from './EnvironmentSelectorPanel';
import { useEnvironmentSelection } from './useEnvironmentSelection';

vi.mock('../../api', () => ({
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);

const baseEnvironment: EnvironmentRecord = {
  id: 'env-1',
  alias: 'gpu-lab',
  display_name: 'GPU Lab',
  description: 'Primary CUDA environment',
  is_seed: false,
  tags: ['gpu'],
  host: 'gpu.example.com',
  port: 22,
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: '/keys/gpu-lab',
  proxy_jump: null,
  proxy_command: null,
  ssh_options: {},
  default_workdir: '/workspace/project',
  preferred_python: 'python3.13',
  preferred_env_manager: 'uv',
  preferred_runtime_notes: 'Use CUDA 12 image',
  task_harness_profile: 'Use the configured environment profile.',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  code_server_path: null,
  latest_detection: null,
};

const secondaryEnvironment: EnvironmentRecord = {
  ...baseEnvironment,
  id: 'env-2',
  alias: 'cpu-lab',
  display_name: 'CPU Lab',
  host: 'cpu.example.com',
};

const defaultEnvironment: EnvironmentRecord = {
  ...baseEnvironment,
  id: 'env-localhost',
  alias: 'localhost',
  display_name: 'Localhost',
  description: 'Seed SSH profile for the current machine.',
  is_seed: true,
  host: '127.0.0.1',
};

function EnvironmentSelectionHarness() {
  const selection = useEnvironmentSelection();

  return <EnvironmentSelectorPanel {...selection} />;
}

beforeEach(() => {
  mockGetEnvironments.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  window.localStorage.clear();
});

describe('EnvironmentSelectorPanel', () => {
  it('prioritizes the settings default over the remembered selection', async () => {
    const settings = createDefaultWebUiSettings();
    settings.projectDefaults.default.defaultEnvironmentId = 'env-1';
    settings.projectDefaults.default.selection.lastEnvironmentId = 'env-2';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    mockGetEnvironments.mockResolvedValue({
      items: [baseEnvironment, defaultEnvironment, secondaryEnvironment],
    });

    renderWithProviders(<EnvironmentSelectionHarness />);

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Active environment' })).toHaveValue('env-1')
    );
  });

  it('falls back to the seed environment and remembers the explicit selection', async () => {
    mockGetEnvironments.mockResolvedValue({
      items: [baseEnvironment, defaultEnvironment, secondaryEnvironment],
    });

    renderWithProviders(<EnvironmentSelectionHarness />);

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Active environment' })).toHaveValue(
        'env-localhost'
      )
    );

    fireEvent.change(screen.getByRole('combobox', { name: 'Active environment' }), {
      target: { value: 'env-2' },
    });

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Active environment' })).toHaveValue('env-2')
    );

    const storedSettings = JSON.parse(
      window.localStorage.getItem(settingsStorageKey) ?? '{}'
    ) as ReturnType<typeof createDefaultWebUiSettings>;
    expect(storedSettings.projectDefaults.default.selection.lastEnvironmentId).toBe('env-2');
  });

  it('falls back to a live environment after the selected one disappears', async () => {
    const settings = createDefaultWebUiSettings();
    settings.projectDefaults.default.selection.lastEnvironmentId = 'env-2';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    mockGetEnvironments.mockResolvedValue({
      items: [secondaryEnvironment, defaultEnvironment, baseEnvironment],
    });

    const firstRender = renderWithProviders(<EnvironmentSelectionHarness />);

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Active environment' })).toHaveValue('env-2')
    );
    firstRender.unmount();

    mockGetEnvironments.mockResolvedValue({ items: [baseEnvironment] });
    renderWithProviders(<EnvironmentSelectionHarness />);

    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Active environment' })).toHaveValue('env-1')
    );
    await waitFor(() => {
      const storedSettings = JSON.parse(
        window.localStorage.getItem(settingsStorageKey) ?? '{}'
      ) as ReturnType<typeof createDefaultWebUiSettings>;
      expect(storedSettings.projectDefaults.default.selection.lastEnvironmentId).toBe('env-1');
    });
  });
});
