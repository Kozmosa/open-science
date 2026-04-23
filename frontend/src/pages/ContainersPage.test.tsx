import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ContainersPage from './ContainersPage';
import type { EnvironmentListResponse, EnvironmentRecord, ProjectEnvironmentReference } from '../types';
import { renderWithProviders } from '../test/render';
import {
  createProjectEnvironmentReference,
  createEnvironment,
  deleteEnvironment,
  detectEnvironment,
  getEnvironments,
  getProjectEnvironmentReferences,
} from '../api';

vi.mock('../api', () => ({
  createProjectEnvironmentReference: vi.fn(),
  createEnvironment: vi.fn(),
  deleteEnvironment: vi.fn(),
  detectEnvironment: vi.fn(),
  getEnvironments: vi.fn(),
  getProjectEnvironmentReferences: vi.fn(),
  updateEnvironment: vi.fn(),
  updateProjectEnvironmentReference: vi.fn(),
}));

const mockGetEnvironments = vi.mocked(getEnvironments);
const mockGetProjectEnvironmentReferences = vi.mocked(getProjectEnvironmentReferences);
const mockCreateProjectEnvironmentReference = vi.mocked(createProjectEnvironmentReference);
const mockCreateEnvironment = vi.mocked(createEnvironment);
const mockDeleteEnvironment = vi.mocked(deleteEnvironment);
const mockDetectEnvironment = vi.mocked(detectEnvironment);

const baseEnvironment: EnvironmentRecord = {
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
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  latest_detection: null,
};

const detectedEnvironment: EnvironmentRecord = {
  ...baseEnvironment,
  latest_detection: {
    environment_id: 'env-1',
    detected_at: '2026-04-21T00:01:00Z',
    status: 'success',
    summary: 'Manual detection completed for gpu-lab.',
    errors: [],
    warnings: [],
    ssh_ok: true,
    hostname: 'gpu.example.com',
    os_info: 'linux',
    arch: 'x86_64',
    workdir_exists: true,
    python: { available: true, version: 'python3.13', path: '/usr/bin/python3.13' },
    conda: { available: false, version: null, path: null },
    uv: { available: true, version: 'mock', path: '/usr/bin/uv' },
    pixi: { available: false, version: null, path: null },
    torch: { available: false, version: null, path: null },
    cuda: { available: false, version: null, path: null },
    gpu_models: [],
    gpu_count: 0,
    claude_cli: { available: true, version: 'mock', path: '/usr/bin/claude' },
    anthropic_env: 'unknown',
  },
};

beforeEach(() => {
  mockGetEnvironments.mockReset();
  mockGetProjectEnvironmentReferences.mockReset();
  mockCreateProjectEnvironmentReference.mockReset();
  mockCreateEnvironment.mockReset();
  mockDeleteEnvironment.mockReset();
  mockDetectEnvironment.mockReset();
  mockGetProjectEnvironmentReferences.mockResolvedValue({ items: [] });
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ContainersPage', () => {
  it('renders the environment list and marks an environment active', async () => {
    const response: EnvironmentListResponse = { items: [baseEnvironment] };
    mockGetEnvironments.mockResolvedValue(response);

    renderWithProviders(<ContainersPage />);

    expect(await screen.findByText('GPU Lab')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use' }));

    expect(screen.getByTestId('active-environment-banner')).toHaveTextContent('gpu-lab');
    expect(window.localStorage.getItem('scholar-agent:selected-environment-id')).toBe('env-1');
  });

  it('creates a new environment through the form', async () => {
    mockGetEnvironments.mockResolvedValue({ items: [] });
    mockCreateEnvironment.mockResolvedValue(baseEnvironment);

    renderWithProviders(<ContainersPage />);

    expect(await screen.findByText('No environments have been created yet.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Alias'), { target: { value: 'gpu-lab' } });
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'GPU Lab' } });
    fireEvent.change(screen.getByLabelText('Host'), { target: { value: 'gpu.example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create environment' }));

    await waitFor(() => expect(mockCreateEnvironment).toHaveBeenCalledTimes(1));
    expect(mockCreateEnvironment).toHaveBeenCalledWith(
      expect.objectContaining({
        alias: 'gpu-lab',
        display_name: 'GPU Lab',
        host: 'gpu.example.com',
        tags: [],
        ssh_options: {},
      })
    );
    expect(await screen.findByText('GPU Lab')).toBeInTheDocument();
  });

  it('sets the selected environment as the current project default', async () => {
    const projectReference: ProjectEnvironmentReference = {
      environment_id: 'env-1',
      is_default: true,
      override_workdir: null,
      override_env_name: null,
      override_env_manager: null,
      override_runtime_notes: null,
      updated_at: '2026-04-21T00:02:00Z',
    };
    mockGetEnvironments.mockResolvedValue({ items: [baseEnvironment] });
    mockCreateProjectEnvironmentReference.mockResolvedValue(projectReference);

    renderWithProviders(<ContainersPage />);

    expect(await screen.findByText('GPU Lab')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use' }));
    fireEvent.click(screen.getByRole('button', { name: 'Set project default' }));

    await waitFor(() =>
      expect(mockCreateProjectEnvironmentReference).toHaveBeenCalledWith(
        expect.objectContaining({
          environment_id: 'env-1',
          is_default: true,
        }),
        'default'
      )
    );
    expect(await screen.findAllByText('Project default')).not.toHaveLength(0);
  });

  it('detects and deletes an environment from the list', async () => {
    mockGetEnvironments.mockResolvedValue({ items: [baseEnvironment] });
    mockDetectEnvironment.mockResolvedValue(detectedEnvironment);
    mockDeleteEnvironment.mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<ContainersPage />);

    expect(await screen.findByText('GPU Lab')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Detect' }));

    expect(await screen.findByText(/Success · Manual detection completed for gpu-lab\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(mockDeleteEnvironment).toHaveBeenCalledWith('env-1'));
  });

  it('shows a backend conflict when deleting a referenced environment', async () => {
    mockGetEnvironments.mockResolvedValue({ items: [baseEnvironment] });
    mockDeleteEnvironment.mockRejectedValue(
      new Error('Request to /environments/env-1 failed with 409 Conflict: Environment is still referenced by a project')
    );
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    renderWithProviders(<ContainersPage />);

    expect(await screen.findByText('GPU Lab')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(
      await screen.findByText(
        /Environment is still referenced by a project/
      )
    ).toBeInTheDocument();
  });
});
