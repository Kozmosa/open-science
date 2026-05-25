import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getCodexDefaults,
  getEnvironments,
  getSkills,
  getWorkspaces,
} from '../../src/api';
import {
  createDefaultWebUiSettings,
  defaultResearchAgentProfileId,
  rawPromptTaskConfigurationId,
  settingsStorageKey,
} from '../../src/settings';
import { renderWithProviders } from '../../src/test/render';
import type { EnvironmentRecord } from '../../src/types';
import SettingsPage from '../../src/pages/SettingsPage';

vi.mock('../../src/components/environment/EnvironmentSelectorPanel', () => ({
  default: () => <div data-testid="environment-selector" />,
}));

vi.mock('../../src/components/terminal/TerminalSessionConsole', () => ({
  default: ({
    attachmentId,
    terminalWsUrl,
  }: {
    attachmentId: string | null;
    terminalWsUrl: string | null;
  }) => (
    <div data-testid="terminal-session-console">
      {attachmentId} {terminalWsUrl}
    </div>
  ),
}));

vi.mock('../../src/api', () => ({ getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getEnvironments: vi.fn(),
  getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getSkillRegistries: vi.fn(),
  getSkills: vi.fn(),
  getWorkspaces: vi.fn(),
  importSkill: vi.fn(),
  installSkillRegistry: vi.fn(),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetCodexDefaults = vi.mocked(getCodexDefaults);
const mockGetSkills = vi.mocked(getSkills);
const mockGetWorkspaces = vi.mocked(getWorkspaces);

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
  window.localStorage.setItem('ainrf.refresh_token', 'mock-refresh-token');
  mockGetEnvironments.mockReset();
  mockGetCodexDefaults.mockReset();
  mockGetSkills.mockReset();
  mockGetWorkspaces.mockReset();
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetCodexDefaults.mockResolvedValue({
    codex_config_toml: 'model = "from-home"\nprovider = "openai"\n',
    codex_auth_json: '{"token":"from-home"}\n',
  });
  mockGetSkills.mockResolvedValue({ items: [] });
  mockGetWorkspaces.mockResolvedValue({ items: [] });
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

  it('hydrates codex profile defaults from local codex settings API', async () => {
    window.localStorage.setItem(
      settingsStorageKey,
      JSON.stringify(createDefaultWebUiSettings())
    );

    renderWithProviders(<SettingsPage />);

    const executionEngineSelect = await screen.findByLabelText('Execution engine');
    fireEvent.change(executionEngineSelect, { target: { value: 'codex-app-server' } });
    fireEvent.change(screen.getByLabelText('Default Research Agent'), {
      target: { value: 'codex-app-server-default' },
    });

    await waitFor(() =>
      expect(screen.getByLabelText('Codex config.toml')).toHaveValue(
        'model = "from-home"\nprovider = "openai"\n'
      )
    );
    expect(screen.getByLabelText('Codex auth.json')).toHaveValue('{"token":"from-home"}\n');
  });

  it('does not overwrite non-empty saved codex profile values with host defaults', async () => {
    const settings = createDefaultWebUiSettings();
    settings.taskConfiguration.defaultExecutionEngineId = 'codex-app-server';
    const codexProfile = settings.taskConfiguration.researchAgentProfiles.find(
      (profile) => profile.profileId === 'codex-app-server-default'
    );
    if (!codexProfile) {
      throw new Error('Missing codex default profile in test fixture');
    }
    codexProfile.codexConfigToml = 'model = "user-saved"\n';
    codexProfile.codexAuthJson = '{"token":"user-saved"}\n';
    settings.taskConfiguration.defaultResearchAgentProfileId = 'codex-app-server-default';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));

    renderWithProviders(<SettingsPage />);

    await waitFor(() =>
      expect(screen.getByLabelText('Codex config.toml')).toHaveValue('model = "user-saved"\n')
    );
    expect(screen.getByLabelText('Codex auth.json')).toHaveValue('{"token":"user-saved"}\n');
  });

  it('preserves intentionally cleared codex profile values across reload', async () => {
    const settings = createDefaultWebUiSettings();
    settings.taskConfiguration.defaultExecutionEngineId = 'codex-app-server';
    const codexProfile = settings.taskConfiguration.researchAgentProfiles.find(
      (profile) => profile.profileId === 'codex-app-server-default'
    );
    if (!codexProfile) {
      throw new Error('Missing codex default profile in test fixture');
    }
    codexProfile.codexConfigToml = '';
    codexProfile.codexAuthJson = '';
    codexProfile.codexConfigTomlSource = 'custom';
    codexProfile.codexAuthJsonSource = 'custom';
    settings.taskConfiguration.defaultResearchAgentProfileId = 'codex-app-server-default';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));

    renderWithProviders(<SettingsPage />);

    await waitFor(() => expect(screen.getByLabelText('Codex config.toml')).toHaveValue(''));
    expect(screen.getByLabelText('Codex auth.json')).toHaveValue('');
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

  it('renders LLM Providers tab and allows adding a provider', async () => {
    renderWithProviders(<SettingsPage />);

    await screen.findByRole('heading', { name: 'Settings' });

    fireEvent.click(screen.getByRole('button', { name: 'LLM Providers' }));

    expect(
      screen.getByText(/No providers configured yet/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Add Provider' }));

    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Test Provider' },
    });
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://api.test.com/' },
    });
    fireEvent.change(screen.getByLabelText('API Key'), {
      target: { value: 'sk-test' },
    });
    fireEvent.change(screen.getByLabelText('Opus Model'), {
      target: { value: 'claude-opus-test' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByText('Test Provider')).toBeInTheDocument();
    });
    expect(screen.getByText('anthropic')).toBeInTheDocument();

    const storedSettings = JSON.parse(
      window.localStorage.getItem(settingsStorageKey) ?? '{}'
    ) as ReturnType<typeof createDefaultWebUiSettings>;
    expect(storedSettings.llmProviders).toHaveLength(1);
    expect(storedSettings.llmProviders[0].name).toBe('Test Provider');
    expect(storedSettings.llmProviders[0].baseUrl).toBe('https://api.test.com/');
  });
});
