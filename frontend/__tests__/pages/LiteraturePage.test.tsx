import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LiteraturePage from '../../src/pages/LiteraturePage';
import { renderWithProviders } from '@/shared/test/render';

vi.mock('@/shared/api', () => ({
  createTask: vi.fn(),
  convertPaperToTask: vi.fn(),
  getCodexDefaults: vi.fn(() =>
    Promise.resolve({ codex_config_toml: null, codex_auth_json: null })
  ),
  getLiteratureSubscriptions: vi.fn(() => Promise.resolve({ items: [] })),
  getWorkspaces: vi.fn(() => Promise.resolve({ items: [] })),
}));

vi.mock('../../src/components/environment', () => ({
  useEnvironmentSelection: () => ({ environments: [] }),
}));

vi.mock('../../src/components/literature/SubscriptionSidebar', () => ({
  default: () => <div>Subscription sidebar</div>,
}));

vi.mock('../../src/components/literature/PaperFeed', () => ({
  default: () => <div>Paper feed</div>,
}));

vi.mock('../../src/components/literature/ConvertToTaskDialog', () => ({
  default: () => null,
}));

describe('LiteraturePage', () => {
  it('applies the standard page inset around the split layout', async () => {
    const { container } = renderWithProviders(<LiteraturePage />, {
      route: '/literature',
    });

    expect(await screen.findByText('Paper feed')).toBeInTheDocument();
    expect(container.firstElementChild).toHaveClass('p-3');
    expect(container.firstElementChild?.querySelector('aside')).toHaveClass('bg-[var(--surface)]');
    expect(container.firstElementChild?.querySelector('main')).toHaveClass('bg-[var(--surface)]');
  });
});
