import { QueryClient } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { getTasks } from './api';
import { LocaleProvider } from './i18n';
import { createDefaultWebUiSettings, settingsStorageKey } from './settings';

vi.mock('./queryClient', async () => {
  const actual = await vi.importActual<typeof import('./queryClient')>('./queryClient');
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

vi.mock('./api', () => ({
  getTasks: vi.fn(),
}));

vi.mock('./pages/TerminalPage', () => ({
  default: () => <div data-testid="terminal-page">terminal-page</div>,
}));

vi.mock('./pages/TasksPage', () => ({
  default: () => <div data-testid="tasks-page">tasks-page</div>,
}));

vi.mock('./pages/EnvironmentsPage', () => ({
  default: () => <div data-testid="environments-page">environments-page</div>,
}));

vi.mock('./pages/WorkspacesPage', () => ({
  default: () => <div data-testid="workspaces-page">workspaces-page</div>,
}));

vi.mock('./pages/SettingsPage', () => ({
  default: () => <div data-testid="settings-page">settings-page</div>,
}));

const mockGetTasks = vi.mocked(getTasks);

const taskBase = {
  task_id: 'task-1',
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

  it('renders non-task routes inside the standard page gutter', async () => {
    window.history.pushState({}, '', '/terminal');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('terminal-page')).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveClass('px-6', 'py-8');
  });

  it('keeps the sidebar fixed while page content scrolls independently', async () => {
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByRole('complementary')).toHaveClass('sticky', 'top-0', 'h-screen');
    expect(screen.getByRole('main')).toHaveClass('overflow-y-auto');
  });

  it('renders a collapsed sidebar by default and live task status summary', async () => {
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
    expect(
      await screen.findByText('Task | Total: 5, Running: 2, Pending: 1, Finished: 2')
    ).toBeInTheDocument();
  });
});
