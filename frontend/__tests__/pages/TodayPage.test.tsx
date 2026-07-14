import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen } from '@testing-library/react';
import { type OverviewRefreshJob, type OverviewSnapshot } from '@features/domain';
import { renderWithProviders } from '@/shared/test/render';
import TodayPage from '../../src/pages/TodayPage';

const domainApiMocks = vi.hoisted(() => ({
  getTodayOverview: vi.fn(),
  requestTodayOverviewRefresh: vi.fn(),
  getOverviewRefreshJob: vi.fn(),
}));

vi.mock('@features/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/auth')>();
  return {
    ...actual,
    useAuth: () => ({
      user: { id: 'today-user', username: 'today', display_name: 'Today User', role: 'user', status: 'active' },
      loading: false,
      login: vi.fn(),
      register: vi.fn(),
      logout: vi.fn(),
    }),
  };
});

vi.mock('@features/domain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@features/domain')>();
  return {
    ...actual,
    ...domainApiMocks,
    useDomainCapabilities: () => ({
      isLoading: false,
      availability: () => ({ available: true, reason: null }),
    }),
  };
});

vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PointerSensor: class PointerSensor {},
  useDraggable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    isDragging: false,
  }),
  useDroppable: () => ({ setNodeRef: vi.fn() }),
  useSensor: () => ({}),
  useSensors: (...sensors: unknown[]) => sensors,
}));

afterEach(() => {
  vi.useRealTimers();
});

const cutoff = '2026-07-14T01:00:00Z';

function snapshot(overrides: Partial<OverviewSnapshot> = {}): OverviewSnapshot {
  return {
    snapshot_id: 'snapshot-1',
    owner_user_id: 'today-user',
    snapshot_date: '2026-07-14',
    data_cutoff_at: cutoff,
    source_status: 'partial',
    attention_required: true,
    cards: [],
    next_scheduled_at: '2026-07-14T22:00:00Z',
    display_cards: [
      {
        id: 'attention',
        data: { items: [{ kind: 'task', task_id: 'task-failed', title: 'Failed analysis', status: 'failed' }] },
        data_cutoff_at: cutoff,
        source_status: 'partial',
        attention_required: true,
        error_summary: 'one source is delayed',
      },
      {
        id: 'progress',
        data: { tasks: [{ task_id: 'task-running', title: 'Running analysis', status: 'running' }] },
        data_cutoff_at: cutoff,
        source_status: 'stale',
        attention_required: false,
        error_summary: null,
      },
      {
        id: 'literature',
        data: { unread_count: 3, updated_count: 1, papers: [{ paper_id: 'paper-1', title: 'Useful paper', primary_category: 'cs.AI' }] },
        data_cutoff_at: cutoff,
        source_status: 'failed',
        attention_required: true,
        error_summary: 'literature projection unavailable',
      },
      {
        id: 'continue',
        data: { items: [{ kind: 'project', id: 'project-1', label: 'Project One', updated_at: cutoff }] },
        data_cutoff_at: cutoff,
        source_status: 'ok',
        attention_required: false,
        error_summary: null,
      },
      {
        id: 'resources',
        data: { environment_count: 2, environments: [{ environment_id: 'env-1', summary: 'GPU warning' }] },
        data_cutoff_at: cutoff,
        source_status: 'partial',
        attention_required: true,
        error_summary: 'resource snapshot stale',
      },
    ],
    ...overrides,
  };
}

function job(status: OverviewRefreshJob['status']): OverviewRefreshJob {
  return {
    job_id: 'overview-job-1',
    owner_user_id: 'today-user',
    trigger: 'manual',
    scheduled_for_date: null,
    status,
    attempt_count: 1,
    retry_count: 0,
    next_retry_at: null,
    last_failure_at: null,
    snapshot_id: status === 'succeeded' || status === 'partial' ? 'snapshot-2' : null,
    source_status: status === 'succeeded' ? 'ok' : status === 'partial' ? 'partial' : null,
    error_summary: status === 'failed' ? 'refresh failed' : null,
    created_at: cutoff,
    started_at: cutoff,
    finished_at: status === 'succeeded' || status === 'partial' || status === 'failed' ? cutoff : null,
    heartbeat_at: cutoff,
  };
}

function renderToday() {
  return renderWithProviders(
    <TodayPage />,
    { route: '/today' },
  );
}

describe('TodayPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    domainApiMocks.getTodayOverview.mockReset();
    domainApiMocks.requestTodayOverviewRefresh.mockReset();
    domainApiMocks.getOverviewRefreshJob.mockReset();
    domainApiMocks.getTodayOverview.mockResolvedValue(snapshot());
  });

  it('keeps Attention first, restores user-scoped card order and exposes source state', async () => {
    window.localStorage.setItem(
      'openscience:preference:today-user:today-card-order',
      JSON.stringify(['resources', 'progress', 'continue', 'literature']),
    );
    renderToday();

    const cards = await screen.findAllByTestId(/^today-card-/);
    expect(cards.map((card) => card.dataset.testid)).toEqual([
      'today-card-attention',
      'today-card-resources',
      'today-card-progress',
      'today-card-continue',
      'today-card-literature',
    ]);
    expect(screen.getByText(/one source is delayed/)).toBeInTheDocument();
    expect(screen.getByText(/literature projection unavailable/)).toBeInTheDocument();
    expect(screen.getAllByText(/Data cutoff:/)).toHaveLength(5);
    expect(screen.getByText('3 unread')).toBeInTheDocument();
  });

  it('shows only the getting-started card when the persisted snapshot has no display data', async () => {
    const emptyCards = snapshot().display_cards!.map((card) => ({
      ...card,
      source_status: 'ok',
      error_summary: null,
      data: card.id === 'literature'
        ? { unread_count: 0, updated_count: 0, papers: [] }
        : card.id === 'resources'
          ? { environment_count: 0, environments: [] }
          : card.id === 'progress'
            ? { tasks: [] }
            : { items: [] },
    }));
    domainApiMocks.getTodayOverview.mockResolvedValue(snapshot({ source_status: 'ok', attention_required: false, display_cards: emptyCards }));

    renderToday();

    expect(await screen.findByText('Start your OpenScience day')).toBeInTheDocument();
    expect(screen.queryByTestId(/^today-card-/)).not.toBeInTheDocument();
  });

  it('polls a refresh job with progressive delays and stops at the terminal state', async () => {
    vi.useFakeTimers();
    let jobReads = 0;
    let overviewReads = 0;
    domainApiMocks.getTodayOverview.mockImplementation(async () => {
      overviewReads += 1;
      return snapshot();
    });
    domainApiMocks.requestTodayOverviewRefresh.mockImplementation(async (idempotencyKey: string) => {
      expect(idempotencyKey).toMatch(/^overview\.today\.refresh:/);
      return job('queued');
    });
    domainApiMocks.getOverviewRefreshJob.mockImplementation(async () => {
      jobReads += 1;
      return job(jobReads === 1 ? 'running' : 'succeeded');
    });
    renderToday();
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Refresh overview' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Refresh overview' }));
    await vi.waitFor(() => expect(screen.getByText('Refresh job: queued')).toBeInTheDocument());
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    await vi.waitFor(() => expect(jobReads).toBe(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    await vi.waitFor(() => expect(jobReads).toBe(2));
    await vi.waitFor(() => expect(screen.getByText('Refresh job: succeeded')).toBeInTheDocument());

    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(jobReads).toBe(2);
    expect(overviewReads).toBeGreaterThanOrEqual(2);
  });

  it('reloads the snapshot when a refresh finishes with partial persisted data', async () => {
    let overviewReads = 0;
    domainApiMocks.getTodayOverview.mockImplementation(async () => {
      overviewReads += 1;
      return snapshot({ source_status: 'partial' });
    });
    domainApiMocks.requestTodayOverviewRefresh.mockResolvedValue(job('partial'));
    renderToday();
    expect(await screen.findByRole('button', { name: 'Refresh overview' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh overview' }));

    await vi.waitFor(() => expect(screen.getByText('Refresh job: partial')).toBeInTheDocument());
    await vi.waitFor(() => expect(overviewReads).toBeGreaterThanOrEqual(2));
    expect(domainApiMocks.getOverviewRefreshJob).not.toHaveBeenCalled();
  });

  it('stops automatic refresh polling after 60 seconds', async () => {
    vi.useFakeTimers();
    let jobReads = 0;
    domainApiMocks.requestTodayOverviewRefresh.mockResolvedValue(job('queued'));
    domainApiMocks.getOverviewRefreshJob.mockImplementation(async () => {
      jobReads += 1;
      return job('running');
    });
    renderToday();
    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Refresh overview' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Refresh overview' }));
    await vi.waitFor(() => expect(screen.getByText('Refresh job: queued')).toBeInTheDocument());
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    await vi.waitFor(() => expect(screen.getByText(/stopped after 60 seconds/)).toBeInTheDocument());
    const readsAtTimeout = jobReads;

    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(jobReads).toBe(readsAtTimeout);
  });
});
