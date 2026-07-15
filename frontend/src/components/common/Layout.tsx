import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import { ConfirmDialog, Sheet } from '@design-system';
import { getRouteDefinition, getVisibleRoutes, type ResolvedAppRoute } from '@/app/routeRegistry';
import { useT } from '@/shared/i18n';
import type { TaskListResponse, TaskSummary } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';
import { useAuth } from '@features/auth';
import { useUserPreference } from '@/shared/hooks/useUserPreference';
import { CommandPalette, NavigationLinks, Sidebar, TopBar } from '@/components/shell';

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function buildTaskStatusSummary(t: ReturnType<typeof useT>, tasks: TaskSummary[] | null): string {
  if (tasks === null) return t('common.taskStatusUnavailable');
  const running = tasks.filter((task) => task.status === 'running' || task.status === 'starting').length;
  const pending = tasks.filter((task) => task.status === 'queued').length;
  const finished = tasks.filter((task) => task.status === 'succeeded' || task.status === 'failed').length;
  return t('common.taskStatusSummary', { total: tasks.length, running, pending, finished });
}

function useCachedTasks(): TaskSummary[] | null {
  const queryClient = useQueryClient();
  const subscribe = useCallback((notify: () => void) => queryClient.getQueryCache().subscribe((event) => {
    if (event.query.queryKey[0] === queryKeys.tasks.all[0]) notify();
  }), [queryClient]);
  const getSnapshot = useCallback(() => {
    const candidates = queryClient.getQueryCache()
      .findAll({ queryKey: queryKeys.tasks.all })
      .filter((query) => Array.isArray((query.state.data as TaskListResponse | undefined)?.items))
      .sort((left, right) => right.state.dataUpdatedAt - left.state.dataUpdatedAt);
    return (candidates[0]?.state.data as TaskListResponse | undefined)?.items ?? null;
  }, [queryClient]);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function resolveRoutes(t: ReturnType<typeof useT>, isAdmin: boolean, navigationOnly: boolean): ResolvedAppRoute[] {
  return getVisibleRoutes(isAdmin, navigationOnly).map((route) => ({
    ...route,
    label: t(route.titleKey),
    description: t(route.descriptionKey),
  }));
}

function Layout({ children }: { children: ReactNode }) {
  const t = useT();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useUserPreference(
    user?.id ?? 'anonymous',
    'sidebar-collapsed',
    true,
    isBoolean,
  );
  const isAdmin = user?.role === 'admin';
  const navigationRoutes = useMemo(() => resolveRoutes(t, isAdmin, true), [isAdmin, t]);
  const commandRoutes = useMemo(() => resolveRoutes(t, isAdmin, false), [isAdmin, t]);
  const taskStatusSummary = buildTaskStatusSummary(t, useCachedTasks());

  useEffect(() => {
    const route = getRouteDefinition(location.pathname);
    document.title = route ? `${t(route.titleKey)} - OpenScience` : t('common.appName');
  }, [location.pathname, t]);

  if (!user) return <>{children}</>;

  return (
    <div className="flex h-screen bg-[var(--osci-color-canvas)] text-[var(--osci-color-text)]">
      <Sidebar
        routes={navigationRoutes}
        collapsed={sidebarCollapsed}
        onCollapsedChange={setSidebarCollapsed}
        user={user}
        onLogout={() => setShowLogoutConfirm(true)}
      />
      <div className="flex h-screen min-w-0 flex-1 flex-col">
        <TopBar
          user={user}
          taskStatusSummary={taskStatusSummary}
          onOpenNavigation={() => setMobileNavigationOpen(true)}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onLogout={() => setShowLogoutConfirm(true)}
        />
        <main className="flex w-full flex-1 flex-col overflow-hidden">{children}</main>
      </div>

      <Sheet open={mobileNavigationOpen} onOpenChange={setMobileNavigationOpen} title={t('common.appName')} side="left">
        <NavigationLinks routes={navigationRoutes} onNavigate={() => setMobileNavigationOpen(false)} />
      </Sheet>
      <CommandPalette open={commandPaletteOpen} onOpenChange={setCommandPaletteOpen} routes={commandRoutes} />
      <ConfirmDialog
        open={showLogoutConfirm}
        onOpenChange={setShowLogoutConfirm}
        title={t('common.confirmLogout')}
        description={t('common.confirmLogoutMessage')}
        confirmLabel={t('common.logOut')}
        danger
        onConfirm={logout}
      />
    </div>
  );
}

export default Layout;
