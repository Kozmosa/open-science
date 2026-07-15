import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import LiteraturePage from '../../src/pages/LiteraturePage';
import { renderWithProviders } from '@/shared/test/render';
import {
  createLiteratureCheck,
  getLiteraturePaper,
  getLiteratureResearchTasks,
  getLiteratureSummary,
  updateLiteraturePaperState,
} from '@/shared/api';

vi.mock('@/shared/api', () => ({
  createLiteratureCheck: vi.fn(() => Promise.resolve({ check_id: 'check-1', status: 'planned' })),
  createLiteratureTopic: vi.fn(),
  deleteLiteratureTopic: vi.fn(),
  getLiteratureOverview: vi.fn(() => Promise.resolve({
    last_successful_check_at: null,
    next_scheduled_check_at: null,
    active_check: null,
    counts: { today: 0, unread: 0, saved: 0, updated: 0 },
  })),
  getLiteraturePapers: vi.fn(() => Promise.resolve({ items: [], next_cursor: null, total: 0 })),
  getLiteratureTopics: vi.fn(() => Promise.resolve({ items: [] })),
  getLiteraturePaper: vi.fn(),
  getLiteratureSummary: vi.fn(),
  getLiteratureResearchTask: vi.fn(),
  getLiteratureResearchTasks: vi.fn(),
  createLiteratureResearchTask: vi.fn(),
  requestLiteratureSummary: vi.fn(),
  updateLiteraturePaperState: vi.fn(),
  previewLiteratureTopic: vi.fn(),
  updateLiteratureTopic: vi.fn(),
}));

describe('LiteraturePage', () => {
  it('renders the canvas inbox with a single source-check action and persistent URL filters', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<LiteraturePage />, { route: '/literature' });

    expect(await screen.findByRole('heading', { name: "Today's literature inbox" })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check latest literature' })).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute('data-page-shell-variant', 'canvas');
    expect(screen.getByRole('button', { name: 'Unread' })).toBeInTheDocument();
    expect(screen.queryByText('My Subscriptions')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Check latest literature' }));
    expect(vi.mocked(createLiteratureCheck)).toHaveBeenCalledWith(
      expect.stringMatching(/^literature\.check\.create:/),
    );
  });

  it('shows and updates user state in the paper detail drawer', async () => {
    const user = userEvent.setup();
    vi.mocked(getLiteraturePaper).mockResolvedValue({
      paper_id: 'paper-1',
      provider: 'arxiv',
      external_id: '2607.00001',
      title: 'Inspectable research paper',
      authors: ['Ada Researcher'],
      abstract: 'A paper abstract.',
      primary_category: 'cs.AI',
      categories: ['cs.AI'],
      published_at: '2026-07-14T08:00:00Z',
      updated_at: '2026-07-15T08:00:00Z',
      source_url: 'https://arxiv.org/abs/2607.00001',
      pdf_url: 'https://arxiv.org/pdf/2607.00001',
      current_version_id: 'version-1',
      matched_topics: [],
      user_state: {
        is_read: false,
        is_saved: true,
        is_ignored: true,
        first_seen_at: '2026-07-14T08:00:00Z',
        last_seen_at: '2026-07-15T08:00:00Z',
        latest_seen_version_id: 'version-1',
      },
      versions: [{
        version_id: 'version-1',
        provider_version: 'v1',
        published_at: '2026-07-14T08:00:00Z',
        updated_at: '2026-07-15T08:00:00Z',
        first_seen_at: '2026-07-14T08:00:00Z',
      }],
    });
    vi.mocked(getLiteratureSummary).mockResolvedValue({ status: 'not_requested' });
    vi.mocked(getLiteratureResearchTasks).mockResolvedValue({ items: [] });
    vi.mocked(updateLiteraturePaperState).mockResolvedValue(undefined as never);

    renderWithProviders(<LiteraturePage />, { route: '/literature?paper=paper-1' });

    expect(await screen.findByRole('heading', { name: 'Your status' })).toBeInTheDocument();
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getByText('Unread')).toBeInTheDocument();
    expect(within(drawer).getByText('Saved')).toBeInTheDocument();
    expect(within(drawer).getByText('Ignored')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Restore to inbox' }));
    expect(vi.mocked(updateLiteraturePaperState)).toHaveBeenCalledWith(
      'paper-1',
      { is_ignored: false },
      expect.stringMatching(/^literature\.paper\.state:/),
    );
  });
});
