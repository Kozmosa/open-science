import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import WorkspacesPage from './WorkspacesPage';
import { renderWithProviders } from '../test/render';

vi.mock('../components', () => ({
  CodeServerCard: () => <div data-testid="code-server-card" />,
  EnvironmentSelectorPanel: () => <div data-testid="environment-selector" />,
  useEnvironmentSelection: () => ({
    selectedEnvironment: null,
    selectedEnvironmentId: null,
    selectedReference: null,
    isLoading: false,
    loadError: null,
    environments: [],
    onSelectEnvironment: vi.fn(),
  }),
}));

describe('WorkspacesPage', () => {
  it('renders page title in the current language and eyebrow in the alternate language', async () => {
    const { unmount } = renderWithProviders(<WorkspacesPage />, {
      route: '/workspaces',
      locale: 'en',
    });

    expect(await screen.findByRole('heading', { name: 'Workspaces' })).toBeInTheDocument();
    expect(screen.getByText('工作区')).toBeInTheDocument();

    unmount();
    renderWithProviders(<WorkspacesPage />, {
      route: '/workspaces',
      locale: 'zh',
    });

    expect(await screen.findByRole('heading', { name: '工作区' })).toBeInTheDocument();
    expect(screen.getByText('WORKSPACES')).toBeInTheDocument();
  });
});
