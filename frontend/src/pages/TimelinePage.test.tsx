import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import TimelinePage from './TimelinePage';
import * as api from '../api';

vi.mock('../api', () => ({
  getSessions: vi.fn(),
  getSession: vi.fn(),
  getProjects: vi.fn(),
}));

const mockGetSessions = vi.mocked(api.getSessions);
const mockGetSession = vi.mocked(api.getSession);
const mockGetProjects = vi.mocked(api.getProjects);

const mockSession = {
  id: 's1',
  project_id: 'p1',
  title: 'Test Session',
  status: 'active' as const,
  task_count: 2,
  total_duration_ms: 15000,
  total_cost_usd: 5.25,
  created_at: '2026-05-17T00:00:00Z',
  updated_at: '2026-05-18T00:00:00Z',
};

const mockAttempts = [
  {
    id: 'a1',
    session_id: 's1',
    task_id: 't1',
    parent_attempt_id: null,
    attempt_seq: 1,
    intervention_reason: null,
    status: 'completed' as const,
    started_at: '2026-05-17T10:00:00Z',
    finished_at: '2026-05-17T10:15:00Z',
    duration_ms: 900000,
    token_usage_json: '{"total":{"input_tokens":1000,"output_tokens":500,"cost_usd":2.50},"source":"agent-sdk"}',
    created_at: '2026-05-17T10:00:00Z',
  },
  {
    id: 'a2',
    session_id: 's1',
    task_id: 't1',
    parent_attempt_id: 'a1',
    attempt_seq: 2,
    intervention_reason: 'fix bugs',
    status: 'completed' as const,
    started_at: '2026-05-17T10:30:00Z',
    finished_at: '2026-05-17T10:40:00Z',
    duration_ms: 600000,
    token_usage_json: '{"total":{"input_tokens":800,"output_tokens":300,"cost_usd":2.75},"source":"claude-session-meta"}',
    created_at: '2026-05-17T10:30:00Z',
  },
];

const mockProject = {
  project_id: 'p1',
  name: 'Test Project',
  description: null,
  default_workspace_id: null,
  default_environment_id: null,
  created_at: '',
  updated_at: '',
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockGetProjects.mockResolvedValue({ items: [mockProject] });
  mockGetSessions.mockResolvedValue({ items: [mockSession] });
  mockGetSession.mockResolvedValue({ ...mockSession, attempts: mockAttempts });
});

describe('TimelinePage', () => {
  it('renders session titles in Gantt labels', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText('Test Session')).toBeInTheDocument();
    });
  });

  it('shows empty state when no sessions', async () => {
    mockGetSessions.mockResolvedValue({ items: [] });
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText('No sessions in this time range')).toBeInTheDocument();
    });
  });

  it('renders project filter with All Projects default', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      expect(screen.getByText('All Projects')).toBeInTheDocument();
    });
  });

  it('shows session count in summary', async () => {
    renderWithProviders(<TimelinePage />);
    const hasSession = await screen.findByText(/1 sessions/);
    if (!hasSession) throw new Error('not found');
  });

  it('renders attempt bars with correct status colors', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      // Completed attempts should have green bar
      const bars = document.querySelectorAll('[class*="bg-green"]');
      expect(bars.length).toBeGreaterThan(0);
    });
  });

  it('renders session cost in label', async () => {
    renderWithProviders(<TimelinePage />);
    await waitFor(() => {
      const costElements = screen.getAllByText(/\$5\.25/);
      expect(costElements.length).toBeGreaterThan(0);
    });
  });
});
