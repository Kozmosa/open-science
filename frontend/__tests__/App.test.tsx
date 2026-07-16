import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../src/App';
import { getTasks } from '@/shared/api';
import { LocaleProvider } from '@/shared/i18n';
import { createDefaultWebUiSettings, settingsStorageKey } from '@/features/settings';

const capabilityState = vi.hoisted(() => ({ overviewAvailable: true }));

vi.mock('../src/index.css', () => ({}));

vi.mock('../src/queryClient', async () => {
  const actual = await vi.importActual<typeof import('../src/queryClient')>('../src/queryClient');
  return {
    ...actual,
    createAppQueryClient: () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            ...actual.appQueryClientDefaultOptions.queries,
            staleTime: 0,
            retry: false,
          },
          mutations: {
            retry: false,
          },
        },
      }),
  };
});

vi.mock('@/features/auth/contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({
    user: { id: 'test-user', username: 'admin', display_name: 'Admin', role: 'admin', status: 'active' },
    loading: false,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock('@features/domain', () => ({
  DomainCapabilityProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useDomainCapabilities: () => ({
    isLoading: false,
    availability: () => ({
      available: capabilityState.overviewAvailable,
      reason: capabilityState.overviewAvailable ? null : 'Today overview is unavailable on this backend.',
    }),
  }),
}));

vi.mock('@/shared/api', () => ({ getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getTasks: vi.fn(),
}));

vi.mock('../src/pages/TerminalPage', () => ({
  default: () => <div data-testid="terminal-page">terminal-page</div>,
}));

vi.mock('../src/pages/TasksPage', () => ({
  default: () => <div data-testid="tasks-page">tasks-page</div>,
}));

vi.mock('../src/pages/EnvironmentsPage', () => ({
  default: () => <div data-testid="environments-page">environments-page</div>,
}));

vi.mock('../src/pages/WorkspacesPage', () => ({
  default: () => <div data-testid="workspaces-page">workspaces-page</div>,
}));

vi.mock('../src/pages/TodayPage', () => ({
  default: () => <div data-testid="today-page">today-page</div>,
}));

vi.mock('../src/pages/SettingsPage', () => ({
  default: () => <div data-testid="settings-page">settings-page</div>,
}));

vi.mock('../src/pages/FileBrowserPage', () => ({
  default: () => <div data-testid="workspace-browser-page">workspace-browser-page</div>,
}));

const mockGetTasks = vi.mocked(getTasks);

const taskBase = {
  task_id: 'task-1',
  project_id: 'default',
  title: 'Task 1',
  task_profile: 'claude-code',
  workspace_summary: {
    workspace_id: 'workspace-default',
    label: 'Repository Default',
    description: null,
    default_workdir: '/workspace/project',
  },
  environment_summary: {
    environment_id: 'env-1',
    alias: 'gpu-lab',
    display_name: 'GPU Lab',
    host: 'gpu.example.com',
    default_workdir: '/workspace/project',
  },
  created_at: '2026-04-23T08:00:00Z',
  updated_at: '2026-04-23T08:01:00Z',
  started_at: null,
  completed_at: null,
  error_summary: null,
  latest_output_seq: 0,
} as const;

describe('App routes', () => {
  beforeEach(() => {
    capabilityState.overviewAvailable = true;
    window.localStorage.clear();
    window.history.pushState({}, '', '/tasks');
    mockGetTasks.mockReset();
    mockGetTasks.mockResolvedValue({ items: [] });
    new QueryClient().clear();
  });

  it('renders the tasks route and shows the Tasks navigation item', async () => {
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Tasks/ })).toHaveAttribute('href', '/tasks');
  });

  it('redirects the root route to the configured default page', async () => {
    const settings = createDefaultWebUiSettings();
    settings.general.defaultRoute = 'workspaces';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    window.history.pushState({}, '', '/');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('workspaces-page')).toBeInTheDocument();
  });

  it('uses Today as the default route for new settings', async () => {
    window.history.pushState({}, '', '/');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('today-page')).toBeInTheDocument();
  });

  it('temporarily falls back to Tasks when Today capability is unavailable without rewriting the preference', async () => {
    capabilityState.overviewAvailable = false;
    const settings = createDefaultWebUiSettings();
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    window.history.pushState({}, '', '/');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(settingsStorageKey) ?? '{}').general.defaultRoute).toBe('today');
  });

  it('renders non-task routes inside the standard page gutter', async () => {
    window.history.pushState({}, '', '/terminal');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('terminal-page')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
  });

  it('keeps the sidebar fixed while page content scrolls independently', async () => {
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByRole('complementary')).toHaveClass('sticky', 'top-0', 'h-screen');
    // Layout <main> is now overflow-hidden; scroll is delegated to SplitPane panels
    expect(screen.getByRole('main')).toHaveClass('overflow-hidden');
  });

  it('renders a collapsed sidebar without polling the full task list', async () => {
    mockGetTasks.mockResolvedValue({
      items: [
        { ...taskBase, task_id: 'task-running', status: 'running' },
        { ...taskBase, task_id: 'task-starting', status: 'starting' },
        { ...taskBase, task_id: 'task-queued', status: 'queued' },
        { ...taskBase, task_id: 'task-succeeded', status: 'succeeded' },
        { ...taskBase, task_id: 'task-failed', status: 'failed' },
      ],
    });

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByLabelText('Expand sidebar')).toBeInTheDocument();
    expect(screen.queryByText(/Task \|/)).not.toBeInTheDocument();
    expect(mockGetTasks).not.toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: 'Browse Files' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('banner')).queryByText('Tasks')).not.toBeInTheDocument();
    expect(document.title).toBe('Tasks - OpenScience');
  });

  it('stores sidebar preference under the authenticated user id', async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    await user.click(await screen.findByRole('button', { name: 'Expand sidebar' }));
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
    expect(window.localStorage.getItem('openscience:preference:test-user:sidebar-collapsed')).toBe('false');
  });

  it('opens the command palette with English keywords and keeps workspace browser as a deep route', async () => {
    const user = userEvent.setup();
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open command palette' }));
    await user.type(screen.getByPlaceholderText('Search pages and actions…'), 'browse files');
    await user.click(screen.getByText('Browse Files'));
    expect(await screen.findByTestId('workspace-browser-page')).toBeInTheDocument();
  });

  it('opens the command palette with Ctrl/Cmd+Shift+P instead of Ctrl/Cmd+K', async () => {
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByText('Ctrl/⌘+Shift+P')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.queryByPlaceholderText('Search pages and actions…')).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'P', metaKey: true, shiftKey: true });
    expect(await screen.findByPlaceholderText('Search pages and actions…')).toBeInTheDocument();
  });
});
