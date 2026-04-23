import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { LocaleProvider } from './i18n';
import { createDefaultWebUiSettings, settingsStorageKey } from './settings';

vi.mock('./pages/TerminalPage', () => ({
  default: () => <div data-testid="terminal-page">terminal-page</div>,
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

vi.mock('./pages/SettingsPage', () => ({
  default: () => <div data-testid="settings-page">settings-page</div>,
}));

describe('App routes', () => {
  beforeEach(() => {
    window.localStorage.clear();
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

  it('redirects the root route to the configured default page', async () => {
    const settings = createDefaultWebUiSettings();
    settings.general.defaultRoute = 'workspaces';
    window.localStorage.setItem(settingsStorageKey, JSON.stringify(settings));
    window.history.pushState({}, '', '/');

    render(
      <LocaleProvider initialLocale="en">
        <App />
      </LocaleProvider>
    );

    expect(await screen.findByTestId('workspaces-page')).toBeInTheDocument();
  });
});
