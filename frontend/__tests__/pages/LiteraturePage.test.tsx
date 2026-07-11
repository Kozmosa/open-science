import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LiteraturePage from '../../src/pages/LiteraturePage';
import { renderWithProviders } from '@/shared/test/render';

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
  previewLiteratureTopic: vi.fn(),
  updateLiteratureTopic: vi.fn(),
}));

vi.mock('../../src/components/literature/PaperCard', () => ({
  default: () => <div>Paper card</div>,
}));

describe('LiteraturePage', () => {
  it('renders the inbox with the standard page inset and a single source-check action', async () => {
    const { container } = renderWithProviders(<LiteraturePage />, { route: '/literature' });

    expect(await screen.findByRole('heading', { name: "Today's literature inbox" })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check latest literature' })).toBeInTheDocument();
    expect(container.firstElementChild).toHaveClass('p-3');
    expect(screen.queryByText('My Subscriptions')).not.toBeInTheDocument();
  });
});
