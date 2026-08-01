import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test-support/render';
import TimelinePage from '../../src/pages/TimelinePage';
import * as taskApi from '@features/tasks/api';
import * as domainApi from '@features/domain';

vi.mock('@features/tasks/api', () => ({ getTasks: vi.fn() }));
vi.mock('@features/domain', async () => {
  const actual = await vi.importActual<typeof import('@features/domain')>('@features/domain');
  return { ...actual, getDomainProjects: vi.fn() };
});

const mockGetTasks = vi.mocked(taskApi.getTasks);
const mockGetProjects = vi.mocked(domainApi.getDomainProjects);

const mockTask = {
  task_id: 'task-1',
  project_id: 'p1',
  workspace_id: 'workspace-1',
  environment_id: 'env-1',
  researcher_type: 'vanilla',
  harness_engine: 'codex-app-server',
  status: 'succeeded' as const,
  title: 'Train model',
  prompt: 'Train the model.',
  created_at: '2026-05-17T10:00:00Z',
  updated_at: '2026-05-17T10:15:00Z',
  started_at: '2026-05-17T10:01:00Z',
  completed_at: '2026-05-17T10:15:00Z',
  owner_user_id: 'user-1',
  latest_output_seq: 8,
  exit_code: 0,
  error_summary: null,
  working_directory: '/workspace/project',
  command: ['codex', 'exec'],
};



const mockProject = {
  project_id: 'p1',
  name: 'Test Project',
  description: null,
  status: 'active' as const,
  is_default: false,
  owner_user_id: 'user-1',
  current_user_role: 'owner' as const,
  created_at: '',
  updated_at: '',
  recent_activity_at: '',
  workspace_count: 0,
  executable_workspace_count: 0,
  task_count: 1,
  active_task_count: 0,
  running_task_count: 0,
  primary_workspace: null,
  attention_required: false,
  attention_reasons: [],
  permissions: { can_edit: true, can_publish: true, can_manage_members: true, can_archive: true, can_unarchive: false, can_create_task: false },
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockGetProjects.mockResolvedValue({ items: [mockProject] });
  mockGetTasks.mockResolvedValue({ items: [mockTask], total: 1 });
});

describe('TimelinePage', () => {
  it('renders task titles in timeline labels from real tasks', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(mockGetTasks).toHaveBeenCalledWith({ includeArchived: false, limit: 1000, sort: 'created' });
      expect(screen.getByText('Train model')).toBeInTheDocument();
    });
  });

  it('shows empty state when no task runs match filters', async () => {
    mockGetTasks.mockResolvedValue({ items: [], total: 0 });
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText('No task runs in this time range')).toBeInTheDocument();
    });
  });

  it('renders project filter with All Projects default', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText('All Projects')).toBeInTheDocument();
    });
  });

  it('shows task count in summary', async () => {
    renderWithProviders(<TimelinePage />);
    const hasTask = await screen.findByText(/1 task runs/);
    if (!hasTask) throw new Error('not found');
  });

  it('renders task bars with status styling', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      const bars = document.querySelectorAll('[data-testid="task-timeline-bar"]');
      expect(bars.length).toBeGreaterThan(0);
    });
  });

  it('renders task engine metadata in label', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText(/codex-app-server/)).toBeInTheDocument();
    });
  });
});
