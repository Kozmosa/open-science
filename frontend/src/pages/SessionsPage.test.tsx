import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '../test/render';
import SessionsPage from './SessionsPage';
import * as api from '../api';

vi.mock('../api', () => ({
  getSessions: vi.fn(),
  getSession: vi.fn(),
}));

const mockGetSessions = vi.mocked(api.getSessions);
const mockGetSession = vi.mocked(api.getSession);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockGetSessions.mockResolvedValue({ items: [] });
  mockGetSession.mockResolvedValue({
    id: 's1',
    project_id: 'p1',
    title: 'Test',
    status: 'active',
    task_count: 0,
    total_duration_ms: 0,
    total_cost_usd: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    attempts: [],
  });
});

describe('SessionsPage', () => {
  it('renders the session list sidebar', async () => {
    mockGetSessions.mockResolvedValue({
      items: [
        {
          id: 's1',
          project_id: 'p1',
          title: 'My Session',
          status: 'active',
          task_count: 2,
          total_duration_ms: 5000,
          total_cost_usd: 1.5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    });

    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getByText('My Session')).toBeInTheDocument();
    });
  });

  it('shows empty state when no sessions', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(screen.getByText('No sessions yet')).toBeInTheDocument();
    });
  });

  it('prompts to select a session initially', async () => {
    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      expect(
        screen.getByText('Select a session to view details'),
      ).toBeInTheDocument();
    });
  });

  it('loads session detail on click', async () => {
    mockGetSessions.mockResolvedValue({
      items: [
        {
          id: 's1',
          project_id: 'p1',
          title: 'My Session',
          status: 'active',
          task_count: 1,
          total_duration_ms: 1000,
          total_cost_usd: 0.5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
    });

    renderWithProviders(<SessionsPage />);

    await waitFor(() => {
      fireEvent.click(screen.getByText('My Session'));
    });

    await waitFor(() => {
      expect(mockGetSession).toHaveBeenCalledWith('s1');
    });
  });
});
