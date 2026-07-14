import { createElement, lazy, Profiler, Suspense, useEffect, type ComponentType, type LazyExoticComponent, type ProfilerOnRenderCallback } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ErrorBoundary, Layout } from './components/common';
import { ToastProvider } from '@design-system';
import { useT } from '@/shared/i18n';
import { createAppQueryClient } from './queryClient';
import { SettingsProvider, useGeneralSettings } from '@features/settings';
import { AuthProvider, useAuth } from '@features/auth';
import { DomainCapabilityProvider } from '@features/domain';
import { reportWebVitals } from '@/shared/utils/reportWebVitals';
import { getRoutePath, ROUTE_REGISTRY, type AppRouteId } from '@/app/routeRegistry';
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
const ChangePasswordPage = lazy(() => import("./pages/ChangePasswordPage"));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));
const LiteraturePage = lazy(() => import('./pages/LiteraturePage'));

const queryClient = createAppQueryClient();

const PROFILER_ENABLED = import.meta.env.VITE_PROFILE === 'true';

const profilerData: Array<{
  id: string;
  phase: string;
  actualDuration: number;
  baseDuration: number;
  commitTime: number;
}> = [];

const onRender: ProfilerOnRenderCallback = (
  id, phase, actualDuration, baseDuration, _startTime, commitTime,
) => {
  if (PROFILER_ENABLED) {
    profilerData.push({ id, phase, actualDuration, baseDuration, commitTime });
    // Keep only last 50 entries to bound memory
    if (profilerData.length > 50) {
      profilerData.splice(0, profilerData.length - 50);
    }
  }
};

// Expose profiler data to window for collection
if (PROFILER_ENABLED && typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__perfProfilerData = profilerData;
}

const routeComponents: Record<AppRouteId, LazyExoticComponent<ComponentType>> = {
  projects: ProjectsPage,
  terminal: TerminalPage,
  tasks: TasksPage,
  workspaces: WorkspacesPage,
  'workspace-browser': FileBrowserPage,
  environments: EnvironmentsPage,
  resources: ResourcesPage,
  sessions: SessionsPage,
  timeline: TimelinePage,
  literature: LiteraturePage,
  settings: SettingsPage,
};

function RootRedirect() {
  const { settings } = useGeneralSettings();
  return <Navigate replace to={getRoutePath(settings.general.defaultRoute) ?? '/terminal'} />;
}

function AuthenticatedRoutes() {
  const t = useT();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  return (
    <Layout>
      <Suspense
        fallback={
          <div className="flex items-center justify-center py-16 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
            {t('common.loading')}
          </div>
        }
      >
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          {ROUTE_REGISTRY.map((route) => (
            <Route
              key={route.id}
              path={route.path}
              element={route.adminOnly && !isAdmin
                ? <Navigate to="/" replace />
                : createElement(routeComponents[route.id])}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

function AppRoutes() {
  const { user, loading } = useAuth();
  const t = useT();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--osci-color-text-muted)]">
        {t('common.loading')}
      </div>
    );
  }

  if (user?.must_change_password) {
    return (
      <Suspense fallback={null}>
        <Routes>
          <Route path="*" element={<ChangePasswordPage />} />
        </Routes>
      </Suspense>
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

  const content = (
    <SettingsProvider userId={user.id}>
      <DomainCapabilityProvider>
        <AuthenticatedRoutes />
      </DomainCapabilityProvider>
    </SettingsProvider>
  );
  return PROFILER_ENABLED ? <Profiler id="AppRoutes" onRender={onRender}>{content}</Profiler> : content;
}

function App() {
  // Start collecting Core Web Vitals (LCP, FCP, INP, CLS) on mount.
  useEffect(() => {
    reportWebVitals();
  }, []);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter>
            <AuthProvider>
              <AppRoutes />
            </AuthProvider>
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
