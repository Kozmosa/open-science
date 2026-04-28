import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspacesPage from './WorkspacesPage';
import { renderWithProviders } from '../test/render';
import {
  createWorkspace,
  deleteWorkspace,
  getWorkspaces,
  updateWorkspace,
} from '../api';
import type { WorkspaceListResponse, WorkspaceRecord } from '../types';

vi.mock('../api', () => ({
  createWorkspace: vi.fn(),
  deleteWorkspace: vi.fn(),
  getWorkspaces: vi.fn(),
  updateWorkspace: vi.fn(),
}));

vi.mock('../components', () => ({
  CodeServerCard: () => <div data-testid="code-server-card" />,
  EnvironmentSelectorPanel: () => <div data-testid="environment-selector" />,
  useEnvironmentSelection: () => ({
    selectedEnvironment: null,
    selectedEnvironmentId: null,
    selectedReference: null,
    isLoading: false,
    loadError: null,
    environments: [],
    onSelectEnvironment: vi.fn(),
  }),
}));

const mockGetWorkspaces = vi.mocked(getWorkspaces);
const mockCreateWorkspace = vi.mocked(createWorkspace);
const mockUpdateWorkspace = vi.mocked(updateWorkspace);
const mockDeleteWorkspace = vi.mocked(deleteWorkspace);

const defaultWorkspace: WorkspaceRecord = {
  workspace_id: 'workspace-default',
  label: 'Repository Default',
  description: 'Seed workspace bound to the current repository checkout.',
  default_workdir: '/workspace/project',
  workspace_prompt: 'Default workspace prompt',
  created_at: '2026-04-27T00:00:00Z',
  updated_at: '2026-04-27T00:00:00Z',
};

const paperWorkspace: WorkspaceRecord = {
  workspace_id: 'workspace-paper',
  label: 'Paper Experiments',
  description: 'Runs for paper figures',
  default_workdir: '/workspace/paper',
  workspace_prompt: 'Focus on reproducible paper experiments.',
  created_at: '2026-04-27T00:01:00Z',
  updated_at: '2026-04-27T00:01:00Z',
};

function workspaceList(items: WorkspaceRecord[]): WorkspaceListResponse {
  return { items };
}

beforeEach(() => {
  mockGetWorkspaces.mockReset();
  mockCreateWorkspace.mockReset();
  mockUpdateWorkspace.mockReset();
  mockDeleteWorkspace.mockReset();
  mockGetWorkspaces.mockResolvedValue(workspaceList([defaultWorkspace, paperWorkspace]));
});

describe('WorkspacesPage', () => {
  it('renders page title in the current language and eyebrow in the alternate language', async () => {
    const { unmount } = renderWithProviders(<WorkspacesPage />, {
      route: '/workspaces',
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Workspaces' })).toBeInTheDocument();
    expect(screen.getByText('工作区')).toBeInTheDocument();

    unmount();
    renderWithProviders(<WorkspacesPage />, {
      route: '/workspaces',
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '工作区' })).toBeInTheDocument();
    expect(screen.getByText('WORKSPACES')).toBeInTheDocument();
  });

  it('renders a workspace manager instead of the shared environment selector or code-server card', async () => {
    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    expect(await screen.findByRole('heading', { name: 'Workspace manager' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Paper Experiments' })).toBeInTheDocument();
    expect(screen.queryByTestId('environment-selector')).not.toBeInTheDocument();
    expect(screen.queryByTestId('code-server-card')).not.toBeInTheDocument();
  });

  it('creates a workspace from the manager form', async () => {
    const createdWorkspace: WorkspaceRecord = {
      ...paperWorkspace,
      workspace_id: 'workspace-created',
      label: 'Created Workspace',
    };
    mockCreateWorkspace.mockResolvedValue(createdWorkspace);
    mockGetWorkspaces
      .mockResolvedValueOnce(workspaceList([defaultWorkspace]))
      .mockResolvedValueOnce(workspaceList([defaultWorkspace, createdWorkspace]));

    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    fireEvent.click(await screen.findByRole('button', { name: 'New workspace' }));
    const labelInput = screen.getByLabelText('Workspace label');
    fireEvent.change(labelInput, {
      target: { value: 'Created Workspace' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'Created from test' },
    });
    fireEvent.change(screen.getByLabelText('Default workdir'), {
      target: { value: '/workspace/created' },
    });
    fireEvent.change(screen.getByLabelText('Workspace prompt'), {
      target: { value: 'Created prompt' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create workspace' }));

    await waitFor(() =>
      expect(mockCreateWorkspace.mock.calls[0]?.[0]).toEqual({
        label: 'Created Workspace',
        description: 'Created from test',
        default_workdir: '/workspace/created',
        workspace_prompt: 'Created prompt',
      })
    );
  });

  it('updates the selected workspace', async () => {
    mockUpdateWorkspace.mockResolvedValue({
      ...paperWorkspace,
      label: 'Updated Workspace',
      description: 'Updated description',
    });

    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    fireEvent.click(await screen.findByRole('button', { name: 'Paper Experiments' }));
    fireEvent.change(screen.getByLabelText('Workspace label'), {
      target: { value: 'Updated Workspace' },
    });
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: 'Updated description' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save workspace' }));

    await waitFor(() => {
      expect(mockUpdateWorkspace.mock.calls[0]?.[0]).toBe('workspace-paper');
      expect(mockUpdateWorkspace.mock.calls[0]?.[1]).toEqual({
        label: 'Updated Workspace',
        description: 'Updated description',
        default_workdir: '/workspace/paper',
        workspace_prompt: 'Focus on reproducible paper experiments.',
      });
    });
  });

  it('deletes a non-default workspace after confirmation', async () => {
    mockDeleteWorkspace.mockResolvedValue(undefined);
    renderWithProviders(<WorkspacesPage />, { route: '/workspaces' });

    fireEvent.click(await screen.findByRole('button', { name: 'Paper Experiments' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete workspace' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(mockDeleteWorkspace.mock.calls[0]?.[0]).toBe('workspace-paper'));
  });
});
