import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement, ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import { ToastProvider } from '../components/common';
import { LocaleProvider, type Locale } from '../i18n';
import { appQueryClientDefaultOptions } from '../queryClient';
import { SettingsProvider } from '../settings';

interface RenderOptions {
  route?: string;
  client?: QueryClient;
  locale?: Locale;
}

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      ...appQueryClientDefaultOptions,
      queries: {
        ...appQueryClientDefaultOptions.queries,
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = '/', client = createTestQueryClient(), locale = 'en' }: RenderOptions = {}
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <LocaleProvider initialLocale={locale}>
        <SettingsProvider>
          <QueryClientProvider client={client}>
            <ToastProvider>
              <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
            </ToastProvider>
          </QueryClientProvider>
        </SettingsProvider>
      </LocaleProvider>
    );
  }

  return render(ui, { wrapper: Wrapper });
}
