import { fireEvent, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import { buildLiteratureTaskCreateFixture } from '@features/tasks/taskCreateContract';
import { renderWithProviders } from '@/shared/test/render';
import { createTask, getSkills } from '@/shared/api';
import { getDomainCapabilities, getDomainProjects, getDomainWorkspaces } from '@features/domain';

vi.mock('@/shared/api', () => ({
  createTask: vi.fn(),
  getSkills: vi.fn(),
}));

vi.mock('@features/domain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/domain')>();
  return {
    ...actual,
    getDomainCapabilities: vi.fn(),
    getDomainProjects: vi.fn(),
    getDomainWorkspaces: vi.fn(),
  };
});

const mockCreateTask = vi.mocked(createTask);
const mockGetSkills = vi.mocked(getSkills);
const mockGetCapabilities = vi.mocked(getDomainCapabilities);
const mockGetProjects = vi.mocked(getDomainProjects);
const mockGetWorkspaces = vi.mocked(getDomainWorkspaces);

const project = {
  project_id: 'project-1',
  name: 'Research project',
  description: null,
  status: 'active' as const,
  is_default: false,
  owner_user_id: 'u1',
  current_user_role: 'owner' as const,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  recent_activity_at: '2026-01-01T00:00:00Z',
  workspace_count: 1,
  executable_workspace_count: 1,
  task_count: 0,
  active_task_count: 0,
  running_task_count: 0,
  primary_workspace: null,
  attention_required: false,
  attention_reasons: [],
  permissions: {
    can_edit: true,
    can_publish: true,
    can_manage_members: true,
    can_archive: true,
    can_unarchive: false,
    can_create_task: true,
  },
};

const workspace = {
  workspace_id: 'workspace-1',
  label: 'Executable workspace',
  description: null,
  canonical_path: '/workspace/research',
  workspace_context: null,
  status: 'active' as const,
  owner_user_id: 'u1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  recent_activity_at: '2026-01-01T00:00:00Z',
  environment: {
    environment_id: 'env-1',
    alias: 'local',
    display_name: 'Local runtime',
    status: 'active' as const,
  },
  project_links: [{
    project_id: 'project-1',
    project_name: 'Research project',
    project_status: 'active' as const,
    current_user_role: 'owner' as const,
    link_status: 'active' as const,
    is_primary: true,
    can_execute: true,
    cannot_execute_reason: null,
  }],
  task_count: 0,
  active_task_count: 0,
  can_execute: true,
  cannot_execute_reason: null,
  can_manage_registry: true,
  git_status: {
    state: 'not_collected' as const,
    branch: null,
    is_dirty: null,
    observed_at: null,
  },
};

beforeEach(() => {
  mockGetProjects.mockResolvedValue({ items: [project] });
  mockGetWorkspaces.mockResolvedValue({ items: [workspace] });
  mockGetSkills.mockResolvedValue({ items: [] });
  mockGetCapabilities.mockResolvedValue({
    domain_contract_version: 2,
    mode: 'v2',
    standard_task_create: true,
    project_context: true,
    workspace_links: true,
    task_attempts: true,
    task_dispatcher: {
      participant_type: 'task-dispatcher',
      ready: true,
      maintenance_active: false,
      maintenance_epoch: null,
      stale_after_seconds: 30,
      registered_participant_ids: ['dispatcher'],
      active_participant_ids: ['dispatcher'],
      fresh_participant_ids: ['dispatcher'],
      stale_participant_ids: [],
    },
    literature_research_task: true,
    overview_snapshot: true,
    overview_snapshot_job_store: true,
    overview_snapshot_planner: {
      job_store_ready: true,
      planner_ready: true,
      planner_status: 'ready',
    },
  });
  mockCreateTask.mockResolvedValue({
    task_id: 'task-created',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    environment_id: 'env-1',
    title: 'Task',
    prompt: 'Inspect the contract',
    status: 'queued',
    owner_user_id: 'u1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    error_summary: null,
  });
});

describe('TaskCreateFlow', () => {
  it('derives Environment from Workspace and submits the restricted v2 payload', async () => {
    renderWithProviders(
      <TaskCreateFlow isOpen source="global" onClose={vi.fn()} />,
      { route: '/tasks' },
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Environment')).toHaveValue('Local runtime (local)');
    });
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'Inspect the contract' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    const [payload, key] = mockCreateTask.mock.calls[0]!;
    expect(payload).toMatchObject({
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      prompt: 'Inspect the contract',
    });
    expect(payload).not.toHaveProperty('environment_id');
    expect(payload).not.toHaveProperty('research_agent_profile');
    expect(key).toMatch(/^task\.create/);
  });

  it('locks source bindings and guides users when no executable Workspace exists', async () => {
    mockGetWorkspaces.mockResolvedValue({ items: [] });
    renderWithProviders(
      <TaskCreateFlow
        isOpen
        source="project"
        lockedProjectId="project-1"
        onClose={vi.fn()}
      />,
      { route: '/projects' },
    );

    expect(await screen.findByLabelText('Project')).toBeDisabled();
    expect(screen.getByText(/No attached Workspace is currently executable/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Register or link Workspace/ })).toBeInTheDocument();
  });

  it('defines a literature fixture without invoking the saga early', () => {
    expect(buildLiteratureTaskCreateFixture({
      paper_id: 'paper-1',
      project_id: 'project-1',
      workspace_id: null,
      title: 'Research paper',
      prompt: 'Investigate the paper',
      preset_id: 'structured-research-default',
    })).toEqual({
      source: 'literature',
      paper_id: 'paper-1',
      project_id: 'project-1',
      workspace_id: null,
      title: 'Research paper',
      prompt: 'Investigate the paper',
      preset_id: 'structured-research-default',
    });
  });

  it('submits the restricted Literature saga selection without a prompt or environment_id', async () => {
    const onLiteratureSubmit = vi.fn(() => Promise.resolve());
    renderWithProviders(
      <TaskCreateFlow
        isOpen
        source="literature"
        initialTitle="Research paper"
        onLiteratureSubmit={onLiteratureSubmit}
        onClose={vi.fn()}
      />,
      { route: '/literature?paper=paper-1' },
    );

    await waitFor(() => expect(screen.getByLabelText('Environment')).toHaveValue('Local runtime (local)'));
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));
    await waitFor(() => expect(onLiteratureSubmit).toHaveBeenCalledWith({
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      task_preset: 'raw-prompt',
      title: 'Research paper',
    }));
    expect(mockCreateTask).not.toHaveBeenCalled();
  });
});
