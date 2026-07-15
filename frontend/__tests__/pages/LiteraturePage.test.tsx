import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import LiteraturePage from '../../src/pages/LiteraturePage';
import { renderWithProviders } from '@/shared/test/render';
import { createLiteratureCheck } from '@/shared/api';

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
});
