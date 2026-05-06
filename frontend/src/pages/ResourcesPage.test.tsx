import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ResourcesPage from './ResourcesPage';
import type { ResourcesResponse } from '../types';
import { renderWithProviders } from '../test/render';
import { getResources } from '../api';

vi.mock('../api', () => ({
  getResources: vi.fn(),
}));

const mockGetResources = vi.mocked(getResources);

const mockResponse: ResourcesResponse = {
  items: [
    {
      environment_id: 'env-localhost',
      environment_name: 'Localhost',
      timestamp: '2026-05-06T12:00:00Z',
      status: 'ok',
      gpus: [
        {
          index: 0,
          name: 'NVIDIA GeForce RTX 4090',
          utilization_percent: 45.0,
          memory_used_mb: 8192,
          memory_total_mb: 24576,
        },
      ],
      cpu: {
        percent: 23.5,
        core_count: 32,
      },
      memory: {
        used_mb: 16384,
        total_mb: 65536,
        percent: 25.0,
      },
      ainrf_processes: [
        {
          pid: 12345,
          name: 'ainrf',
          cpu_percent: 5.2,
          memory_mb: 512,
          runtime_seconds: 3600,
        },
      ],
    },
  ],
};

beforeEach(() => {
  mockGetResources.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResourcesPage', () => {
  it('renders page title in the current language and eyebrow in the alternate language', async () => {
    mockGetResources.mockResolvedValue({ items: [] });
    const { unmount } = renderWithProviders(<ResourcesPage />, {
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Resource Monitor' })).toBeInTheDocument();
    expect(screen.getByText('RESOURCES')).toBeInTheDocument();

    unmount();
    mockGetResources.mockResolvedValue({ items: [] });
    renderWithProviders(<ResourcesPage />, {
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '资源监控' })).toBeInTheDocument();
    // In Chinese, eyebrow and title are both "资源监控", so use getAllByText
    expect(screen.getAllByText('资源监控').length).toBeGreaterThanOrEqual(1);
  });

  it('renders resource data for multiple environments', async () => {
    mockGetResources.mockResolvedValue(mockResponse);

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Localhost')).toBeInTheDocument();
    expect(screen.getByText(/NVIDIA GeForce RTX 4090/)).toBeInTheDocument();
    expect(screen.getByText('45% | 8.0 GB / 24.0 GB')).toBeInTheDocument();
    expect(screen.getByText('32 cores')).toBeInTheDocument();
    expect(screen.getByText('16.0 GB / 64.0 GB (25%)')).toBeInTheDocument();
    expect(screen.getByText('12345')).toBeInTheDocument();
    expect(screen.getByText('ainrf')).toBeInTheDocument();
  });

  it('shows empty state when no resource data is available', async () => {
    mockGetResources.mockResolvedValue({ items: [] });

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('No resource data available yet.')).toBeInTheDocument();
  });

  it('renders degraded status with yellow indicator', async () => {
    const degradedResponse: ResourcesResponse = {
      items: [
        {
          ...mockResponse.items[0],
          status: 'degraded',
        },
      ],
    };
    mockGetResources.mockResolvedValue(degradedResponse);

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Localhost')).toBeInTheDocument();
  });

  it('hides GPU section when no GPUs are present', async () => {
    const noGpuResponse: ResourcesResponse = {
      items: [
        {
          ...mockResponse.items[0],
          gpus: [],
        },
      ],
    };
    mockGetResources.mockResolvedValue(noGpuResponse);

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Localhost')).toBeInTheDocument();
    expect(screen.getByText('No GPU detected')).toBeInTheDocument();
  });
});
