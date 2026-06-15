import {
  Activity,
  BookOpen,
  Boxes,
  ChevronLeft,
  ChevronRight,
  Clock,
  FolderKanban,
  FolderOpen,
  History,
  LayoutGrid,
  ListChecks,
  Settings,
  SquareTerminal,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, useLocation } from 'react-router-dom';
import { getTasks } from '@/shared/api';
import type { TaskSummary } from '@/shared/types';
import LocaleSwitcher from './LocaleSwitcher';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';
import { queryKeys } from '@/shared/api/queryKeys';

interface Props {
  children: ReactNode;
}

interface NavigationItem {
  label: string;
  to: string;
  description: string;
  icon: typeof SquareTerminal;
}

function buildTaskStatusSummary(
  t: ReturnType<typeof useT>,
  tasks: TaskSummary[] | null,
  isError: boolean,
  isLoading: boolean,
): string {
  if (isError) {
    return t('common.taskStatusUnavailable');
  }
  if (isLoading && tasks === null) {
    return t('common.taskStatusLoading');
  }

  const items = tasks ?? [];
  const running = items.filter(
    (task) => task.status === 'running' || task.status === 'starting'
  ).length;
  const pending = items.filter((task) => task.status === 'queued').length;
  const finished = items.filter(
    (task) => task.status === 'succeeded' || task.status === 'failed'
  ).length;

  return t('common.taskStatusSummary', {
    total: items.length,
    running,
    pending,
    finished,
  });
}

function Layout({ children }: Props) {
  const t = useT();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(true);
  const tasksQuery = useQuery({
    queryKey: queryKeys.tasks.all,
    queryFn: () => getTasks(),
    refetchInterval: 5000,
  });
  const taskStatusSummary = buildTaskStatusSummary(
    t,
    tasksQuery.data?.items ?? null,
    tasksQuery.isError,
    tasksQuery.isLoading
  );
  const ROUTE_TITLE_KEYS: Record<string, string> = {
    '/projects': 'navigation.projects.label',
    '/terminal': 'navigation.terminal.label',
    '/tasks': 'navigation.tasks.label',
    '/workspaces': 'navigation.workspaces.label',
    '/workspace-browser': 'navigation.workspaceBrowser.label',
    '/environments': 'navigation.environments.label',
    '/resources': 'navigation.resources.label',
    '/sessions': 'navigation.sessions.label',
    '/timeline': 'navigation.timeline.label',
    '/literature': 'nav.literature',
    '/settings': 'navigation.settings.label',
  };
  const pageTitleKey = ROUTE_TITLE_KEYS[location.pathname] ?? '';
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pageTitle = pageTitleKey ? t(pageTitleKey as any) : '';

  useEffect(() => {
    document.title = pageTitle ? `${pageTitle} - AINRF` : t('common.appName');
  }, [pageTitle, t]);

  const asideWidth = useMemo(
    () => (isCollapsed ? 'w-[56px]' : 'w-[248px]'),
    [isCollapsed]
  );
  const isAdmin = user?.role === 'admin';
  const navigationItems: NavigationItem[] = [
    {
      label: t('navigation.projects.label'),
      to: '/projects',
      description: t('navigation.projects.description'),
      icon: LayoutGrid,
    },
    {
      label: t('navigation.terminal.label'),
      to: '/terminal',
      description: t('navigation.terminal.description'),
      icon: SquareTerminal,
    },
    {
      label: t('navigation.tasks.label'),
      to: '/tasks',
      description: t('navigation.tasks.description'),
      icon: ListChecks,
    },
    {
      label: t('navigation.workspaces.label'),
      to: '/workspaces',
      description: t('navigation.workspaces.description'),
      icon: FolderKanban,
    },
    {
      label: t('navigation.workspaceBrowser.label'),
      to: '/workspace-browser',
      description: t('navigation.workspaceBrowser.description'),
      icon: FolderOpen,
    },
    {
      label: t('navigation.environments.label'),
      to: '/environments',
      description: t('navigation.environments.description'),
      icon: Boxes,
    },
    {
      label: t('navigation.resources.label'),
      to: '/resources',
      description: t('navigation.resources.description'),
      icon: Activity,
    },
    ...(isAdmin
      ? [
          {
            label: t('navigation.sessions.label'),
            to: '/sessions' as const,
            description: t('navigation.sessions.description'),
            icon: History,
          },
          {
            label: t('navigation.timeline.label'),
            to: '/timeline' as const,
            description: t('navigation.timeline.description'),
            icon: Clock,
          },
        ]
      : []),
    {
      label: t('nav.literature'),
      to: '/literature',
      description: t('nav.literature'),
      icon: BookOpen,
    },
    {
      label: t('navigation.settings.label'),
      to: '/settings',
      description: t('navigation.settings.description'),
      icon: Settings,
    },
  ];

  return (
    <div className="h-screen bg-[var(--background)] text-[var(--foreground)]">
      <div className="flex h-screen">
        {/* ── Glass sidebar ────────────────────────────────── */}
        <aside
          className={`${asideWidth} sticky top-0 h-screen shrink-0 overflow-hidden border-r border-[var(--sidebar-border)] bg-[var(--prism-glass)] backdrop-blur-xl text-[var(--sidebar-foreground)] transition-all duration-300 ease-out`}
        >
          <div className="flex h-full flex-col">
            {/* Brand / collapse toggle */}
            <div className="flex h-12 items-center justify-between border-b border-[var(--sidebar-border)] px-3">
              {!isCollapsed && (
                <div className="min-w-0">
                  <p className="truncate text-lg font-semibold tracking-tight text-[var(--foreground)]">
                    {t('common.appName')}
                  </p>
                </div>
              )}
              <button
                type="button"
                onClick={() => setIsCollapsed((v) => !v)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--text-tertiary)] transition hover:bg-[var(--prism-primary-soft)] hover:text-[var(--foreground)]"
                aria-label={
                  isCollapsed
                    ? t('layout.expandSidebar')
                    : t('layout.collapseSidebar')
                }
              >
                {isCollapsed ? (
                  <ChevronRight size={15} />
                ) : (
                  <ChevronLeft size={15} />
                )}
              </button>
            </div>

            {/* User row */}
            {user && (
              <div className="flex items-center gap-2 border-b border-[var(--sidebar-border)] px-3 py-2 text-xs">
                {!isCollapsed && (
                  <span
                    className="truncate text-[var(--text-secondary)]"
                    title={user.display_name}
                  >
                    {user.display_name}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setShowLogoutConfirm(true)}
                  className="ml-auto rounded px-1.5 py-0.5 text-[var(--text-tertiary)] transition hover:bg-[var(--prism-primary-soft)] hover:text-[var(--foreground)]"
                >
                  {t('auth.logout')}
                </button>
              </div>
            )}

            {/* Navigation */}
            <nav className="flex flex-1 flex-col gap-0.5 px-2 py-3">
              {navigationItems.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      [
                        'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-all duration-150',
                        isCollapsed ? 'justify-center' : '',
                        isActive
                          ? 'bg-[var(--prism-primary-soft)] text-[var(--prism-primary)]'
                          : 'text-[var(--text-secondary)] hover:bg-[var(--prism-primary-soft)]/40 hover:text-[var(--foreground)]',
                      ].join(' ')
                    }
                    title={isCollapsed ? item.label : undefined}
                  >
                    <Icon size={18} className="shrink-0" strokeWidth={1.6} />
                    {isCollapsed ? null : (
                      <span className="min-w-0">
                        <span className="block truncate leading-tight">
                          {item.label}
                        </span>
                        <span className="block truncate text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                          {item.description}
                        </span>
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </nav>

            {/* Footer */}
            {!isCollapsed && (
              <div className="border-t border-[var(--sidebar-border)] px-3 py-3">
                <p className="text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                  {t('common.builtBy')}
                </p>
              </div>
            )}
          </div>
        </aside>

        {/* ── Main content area ─────────────────────────────── */}
        <div className="flex h-screen min-w-0 flex-1 flex-col">
          {/* Glass header */}
          <header className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-[var(--border)] bg-[var(--prism-glass)]/90 px-5 backdrop-blur-lg">
            <p className="truncate text-sm font-semibold text-[var(--text)]">
              {pageTitle}
            </p>
            <div className="flex items-center gap-4">
              <p className="hidden truncate text-xs font-medium text-[var(--text-secondary)] sm:block">
                {taskStatusSummary}
              </p>
              <LocaleSwitcher />
            </div>
          </header>

          <main className="flex w-full flex-1 flex-col overflow-hidden">
            {children}
          </main>
        </div>
      </div>

      {/* ── Logout confirm dialog ──────────────────────────── */}
      {showLogoutConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <div className="w-full max-w-xs rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-pane)]">
            <p className="mb-2 text-sm font-medium">
              {t('common.confirmLogout')}
            </p>
            <p className="mb-4 text-xs text-[var(--text-secondary)]">
              {t('common.confirmLogoutMessage')}
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowLogoutConfirm(false)}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs transition hover:bg-[var(--bg-secondary)]"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowLogoutConfirm(false);
                  logout();
                }}
                className="rounded-lg bg-[var(--danger)] px-3 py-1.5 text-xs text-[var(--destructive-foreground)] transition hover:opacity-90"
              >
                {t('common.logOut')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Layout;
