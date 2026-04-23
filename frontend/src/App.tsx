import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ErrorBoundary, Layout, ToastProvider } from './components/common';
import { useT } from './i18n';
import { SettingsProvider, useSettings } from './settings';
import './index.css';

const TerminalPage = lazy(() => import('./pages/TerminalPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const ContainersPage = lazy(() => import('./pages/ContainersPage'));
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchInterval: 10000,
    },
  },
});

const defaultRoutePathById = {
  terminal: '/terminal',
  tasks: '/tasks',
  workspaces: '/workspaces',
  containers: '/containers',
} as const;

function RootRedirect() {
  const { settings } = useSettings();
  return <Navigate replace to={defaultRoutePathById[settings.general.defaultRoute]} />;
}

function App() {
  const t = useT();

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <ToastProvider>
            <BrowserRouter>
              <Layout>
                <Suspense
                  fallback={
                    <div className="px-4 py-8 text-sm text-gray-500 sm:px-6 lg:px-8">
                      {t('common.loading')}
                    </div>
                  }
                >
                  <Routes>
                    <Route path="/" element={<RootRedirect />} />
                    <Route path="/terminal" element={<TerminalPage />} />
                    <Route path="/tasks" element={<TasksPage />} />
                    <Route path="/workspaces" element={<WorkspacesPage />} />
                    <Route path="/containers" element={<ContainersPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
                  </Routes>
                </Suspense>
              </Layout>
            </BrowserRouter>
          </ToastProvider>
        </SettingsProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
