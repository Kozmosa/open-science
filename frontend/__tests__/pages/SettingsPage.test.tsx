import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getDeploymentVersion,
  getFrontendBuildVersion,
  getSearchSettings,
  getSkillDetail,
  getSkillRegistries,
  getSkills,
} from '@features/settings/api';
import { getEnvironments, getProjectEnvironmentReferences } from '@features/environments/api/queries';
import {
  createDefaultWebUiSettings,
  settingsStorageKey,
} from '@/features/settings';
import { renderWithProviders } from '@/test-support/render';
import type { EnvironmentRecord } from '@features/environments/types';
import SettingsPage from '../../src/pages/SettingsPage';

vi.mock('@features/environments/components/EnvironmentSelectorPanel', () => ({
  default: () => <div data-testid="environment-selector" />,
}));

vi.mock('@features/terminal/components/TerminalSessionConsole', () => ({
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

vi.mock('@features/settings/api', () => ({
  getDeploymentVersion: vi.fn(() => Promise.resolve({ short_commit: 'abc123', committed_at: '20260612-2004' })),
  getFrontendBuildVersion: vi.fn(() => Promise.resolve({ short_commit: 'abc123', committed_at: '20260612-2004' })),
  getSkillDetail: vi.fn(),
  getSkillRegistries: vi.fn(),
  getSkills: vi.fn(),
  getSearchSettings: vi.fn(() => Promise.resolve({
    active_backend: 'cc-web-mcp',
    available_backends: [
      { id: 'native', display_name: 'Claude Native', description: 'Built-in', requires_mcp: false },
      { id: 'kindly-web-search', display_name: 'Kindly Web Search', description: 'Serper/Tavily', requires_mcp: true },
      { id: 'cc-web-mcp', display_name: 'CC-Web-MCP', description: 'Lightweight', requires_mcp: true },
    ],
    auto_start_mcp_servers: ['kindly-web-search', 'cc-web-mcp'],
  })),
  updateSearchSettings: vi.fn(() => Promise.resolve({
    active_backend: 'cc-web-mcp',
    available_backends: [],
    auto_start_mcp_servers: [],
  })),
  importSkill: vi.fn(),
  installSkillRegistry: vi.fn(),
}));
vi.mock('@features/environments/api/queries', () => ({
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(() => Promise.resolve({ items: [] })),
}));

vi.mock('@features/domain', () => ({
  getDomainProjects: vi.fn(() => Promise.resolve({
    items: [{ project_id: 'project-user-default', is_default: true }],
  })),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetSkills = vi.mocked(getSkills);
const mockGetDeploymentVersion = vi.mocked(getDeploymentVersion);
const mockGetFrontendBuildVersion = vi.mocked(getFrontendBuildVersion);
const mockGetSkillDetail = vi.mocked(getSkillDetail);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);

const mockGetSkillRegistries = vi.mocked(getSkillRegistries);
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
  mockGetSkills.mockReset();
  mockGetDeploymentVersion.mockReset();
  mockGetDeploymentVersion.mockResolvedValue({ short_commit: 'abc123', committed_at: '20260612-2004' });
  mockGetFrontendBuildVersion.mockReset();
  mockGetFrontendBuildVersion.mockResolvedValue({ short_commit: 'abc123', committed_at: '20260612-2004' });
  mockGetSkillDetail.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  mockGetSkillRegistries.mockReset();
  mockGetSkillRegistries.mockResolvedValue({ items: [] });
  vi.mocked(getSearchSettings).mockReset();
  vi.mocked(getSearchSettings).mockResolvedValue({
    active_backend: 'cc-web-mcp',
    available_backends: [
      { id: 'native', display_name: 'Claude Native', description: 'Built-in', requires_mcp: false },
      { id: 'kindly-web-search', display_name: 'Kindly Web Search', description: 'Serper/Tavily', requires_mcp: true },
      { id: 'cc-web-mcp', display_name: 'CC-Web-MCP', description: 'Lightweight', requires_mcp: true },
    ],
    auto_start_mcp_servers: ['kindly-web-search', 'cc-web-mcp'],
  });
  mockGetEnvironments.mockResolvedValue({ items: [environment] });
  mockGetSkills.mockResolvedValue({ items: [] });
});

describe('SettingsPage', () => {
  it('shows only runtime-backed skill metadata in repository details', async () => {
    mockGetSkills.mockResolvedValue({
      items: [{
        skill_id: 'runtime-skill',
        label: 'Runtime Skill',
        description: 'Mounted by the runtime adapter.',
        inject_mode: 'prompt_only',
        dependencies: ['dependency-skill'],
        package: 'test-package',
      }],
    });
    mockGetSkillDetail.mockResolvedValue({
      skill_id: 'runtime-skill',
      label: 'Runtime Skill',
      description: 'Mounted by the runtime adapter.',
      version: '1.2.3',
      author: 'tester',
      dependencies: ['dependency-skill'],
      inject_mode: 'prompt_only',
      skill_md: '# Runtime Skill',
      package: 'test-package',
    });

    renderWithProviders(<SettingsPage />, { locale: 'en' });

    const repositoryHeading = await screen.findByRole('heading', { name: 'Skill Repository' });
    const repositoryCard =
      repositoryHeading.closest('section') ??
      repositoryHeading.parentElement?.parentElement?.parentElement;
    if (!repositoryCard) throw new Error('Missing skill repository card');
    fireEvent.click(
      await within(repositoryCard).findByRole('button', { name: /Runtime Skill runtime-skill/ })
    );

    expect(await within(repositoryCard).findByText('# Runtime Skill')).toBeInTheDocument();
    expect(within(repositoryCard).getByText('dependency-skill')).toBeInTheDocument();
    expect(within(repositoryCard).queryByText('Preview Settings')).not.toBeInTheDocument();
    expect(within(repositoryCard).queryByText('MCP Servers')).not.toBeInTheDocument();
    expect(within(repositoryCard).queryByText('Hooks')).not.toBeInTheDocument();
    expect(within(repositoryCard).queryByText('Allowed Agents')).not.toBeInTheDocument();
  });

  it('renders localized settings copy without mixing CJK into English', async () => {
    const { unmount } = renderWithProviders(<SettingsPage />, {
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByText('SETTINGS')).toBeInTheDocument();

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

  it('renders backend and frontend deployment versions separately', async () => {
    renderWithProviders(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: 'Deployment Versions' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('deployment-version-backend-commit')).toHaveTextContent('abc123');
      expect(screen.getByTestId('deployment-version-backend-committed-at')).toHaveTextContent('20260612-2004');
      expect(screen.getByTestId('deployment-version-frontend-commit')).toHaveTextContent('abc123');
      expect(screen.getByTestId('deployment-version-frontend-committed-at')).toHaveTextContent('20260612-2004');
    });
    // Matching commits -> no mismatch banner.
    expect(screen.queryByTestId('deployment-version-mismatch')).not.toBeInTheDocument();
  });

  it('flags a mismatch when backend and frontend commits differ', async () => {
    mockGetFrontendBuildVersion.mockResolvedValue({ short_commit: 'feedfa', committed_at: '20260612-2100' });
    renderWithProviders(<SettingsPage />);

    expect(await screen.findByTestId('deployment-version-mismatch')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('deployment-version-backend-commit')).toHaveTextContent('abc123');
      expect(screen.getByTestId('deployment-version-frontend-commit')).toHaveTextContent('feedfa');
    });
  });

  it('does not expose detached browser execution configuration', async () => {
    renderWithProviders(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Task Configuration' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'LLM Providers' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Execution engine')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Default workspace')).not.toBeInTheDocument();
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
      expect(storedSettings.projectDefaults['project-user-default'].defaultEnvironmentId).toBe('env-1');
    });

  });
});
