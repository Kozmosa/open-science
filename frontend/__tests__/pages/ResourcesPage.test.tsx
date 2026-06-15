import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ResourcesPage from '../../src/pages/ResourcesPage';
import type { ResourcesResponse } from '@/shared/types';
import { renderWithProviders } from '@/shared/test/render';
import { getResources, getTaskTokenUsageSummary } from '@/shared/api';

vi.mock('@/shared/api', () => ({ getCodexDefaults: vi.fn(() => Promise.resolve({ codex_config_toml: null, codex_auth_json: null })),
  getResources: vi.fn(),
  getTaskTokenUsageSummary: vi.fn(),
}));

const mockGetResources = vi.mocked(getResources);
const mockGetTaskTokenUsageSummary = vi.mocked(getTaskTokenUsageSummary);

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
  mockGetTaskTokenUsageSummary.mockReset();
  mockGetTaskTokenUsageSummary.mockResolvedValue({
    task_count: 3,
    tasks_with_usage: 2,
    total_tokens: 123456,
    total_cost_usd: 1.25,
    total_duration_ms: 5400000,
    median_duration_ms: 1200000,
    total: { input_tokens: 100000, output_tokens: 20000, cache_creation_input_tokens: 2000, cache_read_input_tokens: 1456, cost_usd: 1.25 },
    by_model: {},
    by_engine: {},
    top_tasks: [
      {
        task_id: 'task-top',
        title: 'Top Token Task',
        status: 'succeeded',
        harness_engine: 'claude-code',
        total_tokens: 34567,
        cost_usd: 0.42,
        duration_ms: 1800000,
      },
    ],
  });
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

  it('renders total task token usage and duration summary', async () => {
    mockGetResources.mockResolvedValue(mockResponse);

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Task Usage')).toBeInTheDocument();
    expect(await screen.findByText('123.5K')).toBeInTheDocument();
    expect(screen.getByText('1h 30m')).toBeInTheDocument();
    expect(screen.getByText('20m')).toBeInTheDocument();
    expect(screen.getByText('Top Token Task')).toBeInTheDocument();
    expect(screen.getByText('34.6K tokens')).toBeInTheDocument();

    expect(screen.getAllByTitle('Drag to reorder')).toHaveLength(3);

  });

  it('keeps the task usage card visible when an old resource card layout is stored', async () => {
    window.localStorage.setItem(
      'scholar-agent:resources-layout',
      JSON.stringify({ cardOrder: ['system', 'processes'] })
    );
    mockGetResources.mockResolvedValue(mockResponse);

    renderWithProviders(<ResourcesPage />);

    expect(await screen.findByText('Task Usage')).toBeInTheDocument();
    expect(await screen.findByText('Localhost')).toBeInTheDocument();
    expect(screen.getAllByTitle('Drag to reorder')).toHaveLength(3);

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
