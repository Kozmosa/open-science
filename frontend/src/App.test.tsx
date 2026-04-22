import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { LocaleProvider } from './i18n';

vi.mock('./pages/DashboardPage', () => ({
  default: () => <div data-testid="dashboard-page">dashboard-page</div>,
}));

vi.mock('./pages/TasksPage', () => ({
  default: () => <div data-testid="tasks-page">tasks-page</div>,
}));

vi.mock('./pages/ContainersPage', () => ({
  default: () => <div data-testid="containers-page">containers-page</div>,
}));

vi.mock('./pages/WorkspacesPage', () => ({
  default: () => <div data-testid="workspaces-page">workspaces-page</div>,
}));

vi.mock('./pages/PlaceholderPage', () => ({
  default: () => <div data-testid="placeholder-page">placeholder-page</div>,
}));

describe('App routes', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/tasks');
  });

  it('renders the tasks route and shows the Tasks navigation item', async () => {
    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('tasks-page')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Tasks/ })).toHaveAttribute('href', '/tasks');
  });
});
