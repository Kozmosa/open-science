import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../../src/test/render';
import SessionsPage from '../../src/pages/SessionsPage';
import * as api from '../../src/api';

vi.mock('../../src/api', () => ({ getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getTasks: vi.fn(),
  getTask: vi.fn(),
}));

const mockGetTasks = vi.mocked(api.getTasks);
const mockGetTask = vi.mocked(api.getTask);

const taskSummary = {
  task_id: 'task-1',
  project_id: 'p1',
  workspace_id: 'workspace-1',
  environment_id: 'env-1',
  researcher_type: 'vanilla',
  harness_engine: 'codex-app-server',
  status: 'succeeded' as const,
  title: 'Train model',
  prompt: 'Train the model.',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:05:00Z',
  started_at: '2026-01-01T00:01:00Z',
  completed_at: '2026-01-01T00:05:00Z',
  owner_user_id: 'user-1',
  latest_output_seq: 12,
  exit_code: 0,
  error_summary: null,
  working_directory: '/workspace/project',
  command: ['codex', 'exec'],
};

const taskRecord = {
  ...taskSummary,
  binding: {
    project_id: 'p1',
    workspace_id: 'workspace-1',
    environment_id: 'env-1',
    profile_id: 'vanilla',
    title: 'Train model',
    task_input: 'Train the model.',
    resolved_workdir: '/workspace/project',
    environment: { id: 'env-1', alias: 'gpu-lab', display_name: 'GPU Lab', target_kind: 'ssh', working_directory: '/workspace/project' },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockGetTasks.mockResolvedValue({ items: [taskSummary], total: 1 });
  mockGetTask.mockResolvedValue(taskRecord);
});

describe('SessionsPage', () => {
  it('renders the task run list sidebar from real tasks', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(mockGetTasks).toHaveBeenCalledWith({ includeArchived: false, limit: 200, sort: 'updated' });
      expect(screen.getByText('Train model')).toBeInTheDocument();
      expect(screen.getByText(/codex-app-server/)).toBeInTheDocument();
    });
  });

  it('shows empty state when no task runs exist', async () => {
    mockGetTasks.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getByText('No task runs yet')).toBeInTheDocument();
    });
  });

  it('prompts to select a task run initially', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(
        screen.getByText('Select a task run to view details'),
      ).toBeInTheDocument();
    });
  });

  it('loads task detail on click', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByText('Train model'));
    });

    await waitFor(() => {
      expect(mockGetTask).toHaveBeenCalledWith('task-1');
      expect(screen.getByText('Train the model.')).toBeInTheDocument();
      expect(screen.getByText('/workspace/project')).toBeInTheDocument();
    });
  });
});
