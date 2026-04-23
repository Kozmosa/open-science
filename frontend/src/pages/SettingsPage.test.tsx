import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getEnvironments } from '../api';
import { createDefaultWebUiSettings, settingsStorageKey } from '../settings';
import { renderWithProviders } from '../test/render';
import type { EnvironmentRecord } from '../types';
import SettingsPage from './SettingsPage';

vi.mock('../api', () => ({
  getEnvironments: vi.fn(),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);

const environment: EnvironmentRecord = {
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
  latest_detection: null,
};

beforeEach(() => {
  window.localStorage.clear();
  mockGetEnvironments.mockReset();
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
});

describe('SettingsPage', () => {
  it('falls back from an invalid document and persists section saves', async () => {
    window.localStorage.setItem(settingsStorageKey, '{invalid');

    renderWithProviders(<SettingsPage />);

    expect(
      await screen.findByText(
        /The local settings document was missing fields, invalid, or no longer compatible/
      )
    ).toBeInTheDocument();

    const generalSection = screen
      .getByRole('heading', { name: 'General Preferences' })
      .closest('section');
    expect(generalSection).not.toBeNull();

    fireEvent.change(within(generalSection as HTMLElement).getByLabelText('Default route'), {
      target: { value: 'tasks' },
    });
    fireEvent.change(within(generalSection as HTMLElement).getByLabelText('Terminal font size'), {
      target: { value: '16' },
    });
    fireEvent.click(
      within(generalSection as HTMLElement).getByRole('button', { name: 'Save changes' })
    );

    await waitFor(() => {
      const storedSettings = JSON.parse(
        window.localStorage.getItem(settingsStorageKey) ?? '{}'
      ) as ReturnType<typeof createDefaultWebUiSettings>;
      expect(storedSettings.general.defaultRoute).toBe('tasks');
      expect(storedSettings.general.terminal.fontSize).toBe(16);
    });

    const projectSection = screen
      .getByRole('heading', { name: 'Project Defaults' })
      .closest('section');
    expect(projectSection).not.toBeNull();

    fireEvent.change(
      within(projectSection as HTMLElement).getByLabelText('Default environment'),
      {
        target: { value: 'env-1' },
      }
    );
    fireEvent.click(
      within(projectSection as HTMLElement).getAllByRole('button', { name: 'Save changes' })[0] as
        HTMLButtonElement
    );

    await waitFor(() => {
      const storedSettings = JSON.parse(
        window.localStorage.getItem(settingsStorageKey) ?? '{}'
      ) as ReturnType<typeof createDefaultWebUiSettings>;
      expect(storedSettings.projectDefaults.default.defaultEnvironmentId).toBe('env-1');
    });

    const environmentCard = screen
      .getByRole('heading', { name: 'gpu-lab · GPU Lab' })
      .closest('section');
    expect(environmentCard).not.toBeNull();

    fireEvent.change(
      within(environmentCard as HTMLElement).getByLabelText('gpu-lab Title template'),
      {
        target: { value: 'GPU daily check' },
      }
    );
    fireEvent.change(
      within(environmentCard as HTMLElement).getByLabelText('gpu-lab Task input template'),
      {
        target: { value: 'Check CUDA, torch, and disk status.' },
      }
    );
    fireEvent.click(
      within(environmentCard as HTMLElement).getByRole('button', { name: 'Save changes' })
    );

    await waitFor(() => {
      const storedSettings = JSON.parse(
        window.localStorage.getItem(settingsStorageKey) ?? '{}'
      ) as ReturnType<typeof createDefaultWebUiSettings>;
      expect(storedSettings.projectDefaults.default.environmentDefaults['env-1']).toEqual({
        titleTemplate: 'GPU daily check',
        taskInputTemplate: 'Check CUDA, torch, and disk status.',
      });
    });
  });
});
