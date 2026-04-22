import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ErrorBoundary, Layout, ToastProvider } from './components/common';
import { useT } from './i18n';
import DashboardPage from './pages/DashboardPage';
import TasksPage from './pages/TasksPage';
import ContainersPage from './pages/ContainersPage';
import WorkspacesPage from './pages/WorkspacesPage';
import PlaceholderPage from './pages/PlaceholderPage';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchInterval: 10000,
    },
  },
});

function App() {
  const t = useT();

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter>
            <Layout>
              <Routes>
                <Route path="/" element={<Navigate replace to="/terminal" />} />
                <Route path="/terminal" element={<DashboardPage />} />
                <Route path="/tasks" element={<TasksPage />} />
                <Route path="/workspaces" element={<WorkspacesPage />} />
                <Route path="/containers" element={<ContainersPage />} />
                <Route
                  path="/settings"
                  element={
                    <PlaceholderPage
                      eyebrow={t('pages.placeholder.eyebrow')}
                      title={t('pages.placeholder.title')}
                      description={t('pages.placeholder.description')}
                      badgeLabel={t('pages.placeholder.badge')}
                    />
                  }
                />
              </Routes>
            </Layout>
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
