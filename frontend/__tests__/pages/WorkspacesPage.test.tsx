import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspacesPage from '../../src/pages/WorkspacesPage';
import { renderWithProviders } from '@/shared/test/render';
import { getEnvironments, unregisterWorkspace, updateWorkspace } from '@/shared/api';
import {
  attachDomainWorkspace,
  createDomainWorkspace,
  getDomainProjects,
  getDomainWorkspaces,
  setDomainPrimaryWorkspace,
  type DomainWorkspaceProjection,
} from '@features/domain';

vi.mock('@/shared/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/api')>('@/shared/api');
  return {
    ...actual,
    getEnvironments: vi.fn(),
    unregisterWorkspace: vi.fn(),
    updateWorkspace: vi.fn(),
  };
});

vi.mock('@features/domain', async () => {
  const actual = await vi.importActual<typeof import('@features/domain')>('@features/domain');
  return {
    ...actual,
    attachDomainWorkspace: vi.fn(),
    createDomainWorkspace: vi.fn(),
    getDomainProjects: vi.fn(),
    getDomainWorkspaces: vi.fn(),
    setDomainPrimaryWorkspace: vi.fn(),
  };
});

vi.mock('@features/auth', async () => {
  const actual = await vi.importActual<typeof import('@features/auth')>('@features/auth');
  return {
    ...actual,
    useAuth: () => ({
      user: { id: 'user-1', username: 'alice', display_name: 'Alice', role: 'user', status: 'active' },
      loading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

vi.mock('@features/tasks/components/TaskCreateFlow', () => ({
  default: () => null,
}));

const workspace: DomainWorkspaceProjection = {
  workspace_id: 'workspace-1',
  label: 'Paper Experiments',
  description: 'Reproducible figures',
  canonical_path: '/srv/papers/experiment',
  workspace_context: 'Keep figure generation deterministic.',
  status: 'active',
  owner_user_id: 'user-1',
  created_at: '2026-07-14T00:00:00Z',
  updated_at: '2026-07-14T01:00:00Z',
  recent_activity_at: '2026-07-14T01:00:00Z',
  environment: {
    environment_id: 'env-1',
    alias: 'gpu-lab',
    display_name: 'GPU Lab',
    status: 'active',
  },
  project_links: [{
    project_id: 'project-1',
    project_name: 'Paper Project',
    project_status: 'active',
    current_user_role: 'owner',
    link_status: 'active',
    is_primary: true,
    can_execute: false,
    cannot_execute_reason: 'environment_grant_missing',
  }],
  task_count: 8,
  active_task_count: 2,
  can_execute: false,
  cannot_execute_reason: 'environment_grant_missing',
  can_manage_registry: true,
  git_status: {
    state: 'available',
    branch: 'feat/paper',
    is_dirty: true,
    observed_at: '2026-07-14T01:00:00Z',
  },
};

const mockGetDomainWorkspaces = vi.mocked(getDomainWorkspaces);
const mockGetDomainProjects = vi.mocked(getDomainProjects);
const mockGetEnvironments = vi.mocked(getEnvironments);
const mockCreateDomainWorkspace = vi.mocked(createDomainWorkspace);
const mockAttachDomainWorkspace = vi.mocked(attachDomainWorkspace);
const mockSetDomainPrimaryWorkspace = vi.mocked(setDomainPrimaryWorkspace);
const mockUpdateWorkspace = vi.mocked(updateWorkspace);
const mockUnregisterWorkspace = vi.mocked(unregisterWorkspace);

beforeEach(() => {
  vi.clearAllMocks();
  mockGetDomainWorkspaces.mockResolvedValue({ items: [workspace] });
  mockGetDomainProjects.mockResolvedValue({ items: [{
    project_id: 'project-1',
    name: 'Paper Project',
    description: null,
    status: 'active',
    is_default: false,
    owner_user_id: 'user-1',
    current_user_role: 'owner',
    created_at: '2026-07-14T00:00:00Z',
    updated_at: '2026-07-14T00:00:00Z',
    recent_activity_at: '2026-07-14T00:00:00Z',
    workspace_count: 1,
    executable_workspace_count: 0,
    task_count: 8,
    active_task_count: 2,
    running_task_count: 1,
    primary_workspace: null,
    attention_required: true,
    attention_reasons: ['environment_grant_missing'],
    permissions: { can_edit: true, can_publish: true, can_manage_members: true, can_archive: true, can_unarchive: false, can_create_task: false },
  }] });
  mockGetEnvironments.mockResolvedValue({ items: [{
    id: 'env-1', alias: 'gpu-lab', display_name: 'GPU Lab', description: null, is_seed: false,
    tags: [], host: 'gpu.example', port: 22, user: 'alice', auth_kind: 'agent', identity_file: null,
    proxy_jump: null, proxy_command: null, ssh_options: {}, default_workdir: '/srv', preferred_python: null,
    preferred_env_manager: null, preferred_runtime_notes: null, task_harness_profile: null,
    created_at: null, updated_at: null, latest_detection: null,
  }] });
});

describe('WorkspacesPage', () => {
  it('renders the domain projection and distinguishes linked from executable', async () => {
    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    expect(await screen.findByRole('heading', { name: 'Paper Experiments' })).toBeInTheDocument();
    expect(screen.getByText('GPU Lab (gpu-lab)')).toBeInTheDocument();
    expect(screen.getAllByText(/environment_grant_missing/)).toHaveLength(2);
    expect(screen.getByText('feat/paper · dirty')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new task/i })).toBeDisabled();
  });

  it('registers Environment, canonical path, context, Project attachment and Primary in order', async () => {
    const user = userEvent.setup();
    mockCreateDomainWorkspace.mockResolvedValue({ workspace_id: 'workspace-new' });
    mockUpdateWorkspace.mockResolvedValue({} as never);
    mockAttachDomainWorkspace.mockResolvedValue({});
    mockSetDomainPrimaryWorkspace.mockResolvedValue({});
    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    await user.click(await screen.findByRole('button', { name: 'Register workspace' }));
    await user.selectOptions(screen.getByLabelText('Environment'), 'env-1');
    await user.type(screen.getByLabelText('Canonical path'), '/srv/papers/new');
    await user.type(screen.getByLabelText('Workspace name'), 'New Workspace');
    await user.type(screen.getByLabelText('Workspace context'), 'Use the locked dataset.');
    await user.selectOptions(screen.getByLabelText('Optional initial Project'), 'project-1');
    await user.click(screen.getByLabelText('Make this the Project Primary Workspace'));
    await user.click(screen.getAllByRole('button', { name: 'Register workspace' }).at(-1)!);

    await waitFor(() => expect(mockCreateDomainWorkspace).toHaveBeenCalledWith({
      environment_id: 'env-1',
      canonical_path: '/srv/papers/new',
      label: 'New Workspace',
    }, expect.stringContaining('workspace.register')));
    expect(mockUpdateWorkspace).toHaveBeenCalledWith('workspace-new', { workspace_prompt: 'Use the locked dataset.' }, expect.any(String));
    expect(mockAttachDomainWorkspace).toHaveBeenCalledWith('project-1', 'workspace-new', expect.any(String));
    expect(mockSetDomainPrimaryWorkspace).toHaveBeenCalledWith('project-1', 'workspace-new', expect.any(String));
  });

  it('states that unregister never deletes the disk directory and uses an idempotency key', async () => {
    const user = userEvent.setup();
    mockUnregisterWorkspace.mockResolvedValue(undefined);
    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    await user.click(await screen.findByRole('button', { name: 'Unregister' }));
    expect(screen.getByText(/does not delete the directory or any files on disk/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Unregister' }));

    await waitFor(() => expect(mockUnregisterWorkspace).toHaveBeenCalledWith('workspace-1', expect.stringMatching(/^workspace\.unregister:/)));
  });
});
