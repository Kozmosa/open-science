import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getEnvironments, installEnvironmentCodeServer } from '../api';
import {
  createDefaultWebUiSettings,
  defaultResearchAgentProfileId,
  rawPromptTaskConfigurationId,
  settingsStorageKey,
} from '../settings';
import { renderWithProviders } from '../test/render';
import type { EnvironmentRecord } from '../types';
import SettingsPage from './SettingsPage';

vi.mock('../components/environment/EnvironmentSelectorPanel', () => ({
  default: () => <div data-testid="environment-selector" />,
}));

vi.mock('../api', () => ({
  getEnvironments: vi.fn(),
  installEnvironmentCodeServer: vi.fn(),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);
const mockInstallEnvironmentCodeServer = vi.mocked(installEnvironmentCodeServer);

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
  code_server_path: null,
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  latest_detection: null,
};

beforeEach(() => {
  window.localStorage.clear();
  mockGetEnvironments.mockReset();
  mockInstallEnvironmentCodeServer.mockReset();
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
});

describe('SettingsPage', () => {
  it('renders page title in the current language and eyebrow in the alternate language', async () => {
    const { unmount } = renderWithProviders(<SettingsPage />, {
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();

    unmount();
    renderWithProviders(<SettingsPage />, {
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '设置' })).toBeInTheDocument();
    expect(screen.getByText('SETTINGS')).toBeInTheDocument();
  });

  it('renders the shared environment selector between general and project defaults', async () => {
    renderWithProviders(<SettingsPage />);

    const generalHeading = await screen.findByRole('heading', { name: 'General Preferences' });
    const selector = screen.getByTestId('environment-selector');
    const projectHeading = screen.getByRole('heading', { name: 'Project Defaults' });

    expect(generalHeading.compareDocumentPosition(selector) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(selector.compareDocumentPosition(projectHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

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
        researchAgentProfileId: defaultResearchAgentProfileId,
        taskConfigurationId: rawPromptTaskConfigurationId,
      });
    });
  });

  it('renders code-server install state and installs for the selected environment', async () => {
    const installedEnvironment: EnvironmentRecord = {
      ...environment,
      code_server_path:
        '~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server',
    };
    mockInstallEnvironmentCodeServer.mockResolvedValue({
      environment: installedEnvironment,
      installed: true,
      version: '4.117.0',
      install_dir: '~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64',
      code_server_path: installedEnvironment.code_server_path as string,
      execution_mode: 'ssh',
      already_installed: false,
      detail: 'code-server installed',
    });
    mockGetEnvironments
      .mockResolvedValueOnce({ items: [environment] })
      .mockResolvedValueOnce({ items: [installedEnvironment] });

    renderWithProviders(<SettingsPage />);

    const installSection = (
      await screen.findByRole('heading', { name: 'Code-server installer' })
    ).closest('section');
    expect(installSection).not.toBeNull();
    await within(installSection as HTMLElement).findByText('gpu-lab · GPU Lab');
    expect(within(installSection as HTMLElement).getByText('Not installed')).toBeInTheDocument();

    fireEvent.click(
      within(installSection as HTMLElement).getByRole('button', { name: 'Install code-server' })
    );

    await waitFor(() => {
      expect(mockInstallEnvironmentCodeServer).toHaveBeenCalled();
    });
    expect(mockInstallEnvironmentCodeServer.mock.calls[0]?.[0]).toBe('env-1');
    expect(
      await within(installSection as HTMLElement).findByText(
        '~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server'
      )
    ).toBeInTheDocument();
  });

  it('shows existing code-server path when already installed', async () => {
    mockGetEnvironments.mockResolvedValue({
      items: [
        {
          ...environment,
          code_server_path:
            '~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server',
        },
      ],
    });

    renderWithProviders(<SettingsPage />);

    const installSection = (
      await screen.findByRole('heading', { name: 'Code-server installer' })
    ).closest('section');
    expect(installSection).not.toBeNull();
    await within(installSection as HTMLElement).findByText('gpu-lab · GPU Lab');
    expect(
      within(installSection as HTMLElement).getByText(
        '~/.local/ainrf/code-server/code-server-4.117.0-linux-amd64/bin/code-server'
      )
    ).toBeInTheDocument();
  });
});
