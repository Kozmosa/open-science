import { lazy, Suspense } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ErrorBoundary, Layout, ToastProvider } from './components/common';
import { useT } from './i18n';
import { createAppQueryClient } from './queryClient';
import { SettingsProvider, useSettings } from './settings';
import './index.css';

const TerminalPage = lazy(() => import('./pages/TerminalPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const EnvironmentsPage = lazy(() => import('./pages/EnvironmentsPage'));
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage'));
const FileBrowserPage = lazy(() => import('./pages/FileBrowserPage'));
const ResourcesPage = lazy(() => import('./pages/ResourcesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));

const queryClient = createAppQueryClient();

const defaultRoutePathById = {
  projects: '/projects',
  terminal: '/terminal',
  tasks: '/tasks',
  workspaces: '/workspaces',
  environments: '/environments',
} as const;

function RootRedirect() {
  const { settings } = useSettings();
  return <Navigate replace to={defaultRoutePathById[settings.general.defaultRoute]} />;
}

function AppRoutes() {
  const t = useT();
  const location = useLocation();
  const isTaskRoute = location.pathname === '/tasks';

  return (
    <Layout edgeToEdge={isTaskRoute}>
      <Suspense
        fallback={
          <div className="flex items-center justify-center py-16 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
            {t('common.loading')}
          </div>
        }
      >
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/terminal" element={<TerminalPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/workspaces" element={<WorkspacesPage />} />
          <Route path="/workspace-browser" element={<FileBrowserPage />} />
          <Route path="/environments" element={<EnvironmentsPage />} />
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <ToastProvider>
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
          </ToastProvider>
        </SettingsProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
