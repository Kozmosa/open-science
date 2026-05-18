import { lazy, Suspense } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { ErrorBoundary, Layout, ToastProvider } from './components/common';
import { useT } from './i18n';
import { createAppQueryClient } from './queryClient';
import { SettingsProvider, useSettings } from './settings';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import './index.css';

const TerminalPage = lazy(() => import('./pages/TerminalPage'));
const TasksPage = lazy(() => import('./pages/TasksPage'));
const EnvironmentsPage = lazy(() => import('./pages/EnvironmentsPage'));
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage'));
const FileBrowserPage = lazy(() => import('./pages/FileBrowserPage'));
const ResourcesPage = lazy(() => import('./pages/ResourcesPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'));
const SessionsPage = lazy(() => import('./pages/SessionsPage'));
const TimelinePage = lazy(() => import('./pages/TimelinePage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));

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

function AuthenticatedRoutes() {
  const t = useT();
  const location = useLocation();
  const isEdgeToEdge = location.pathname === '/tasks' || location.pathname === '/projects';

  return (
    <Layout edgeToEdge={isEdgeToEdge}>
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
          <Route path="/sessions" element={<SessionsPage />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

function AppRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-gray-400 text-sm">
        Loading...
      </div>
    );
  }

  if (!user) {
    return (
      <Suspense fallback={null}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </Suspense>
    );
  }

  return <AuthenticatedRoutes />;
}

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SettingsProvider>
          <ToastProvider>
            <BrowserRouter>
              <AuthProvider>
                <AppRoutes />
              </AuthProvider>
            </BrowserRouter>
          </ToastProvider>
        </SettingsProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
