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
import { useAuth } from '../../contexts/AuthContext';

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
  const running = items.filter((task) => task.status === 'running' || task.status === 'starting').length;
  const pending = items.filter((task) => task.status === 'queued').length;
  const finished = items.filter(
    (task) => task.status === 'succeeded' || task.status === 'failed'
  ).length;

  return t('common.taskStatusSummary', { total: items.length, running, pending, finished });
}

function Layout({ children }: Props) {
  const t = useT();
  const location = useLocation();
  const { user, logout } = useAuth();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(true);
  const tasksQuery = useQuery({
    queryKey: ['tasks'],
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

  const asideWidth = useMemo(() => (isCollapsed ? 'w-[56px]' : 'w-[248px]'), [isCollapsed]);
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
        <aside
          className={`${asideWidth} sticky top-0 h-screen shrink-0 overflow-hidden border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-[var(--sidebar-foreground)] transition-all duration-200 ease-out`}
        >
          <div className="flex h-full flex-col">
            <div className="flex h-12 items-center justify-between border-b border-[var(--sidebar-border)] px-3">
            {!isCollapsed && (
              <div className="min-w-0">
                <p className="truncate text-lg font-bold tracking-tight">{t('common.appName')}</p>
              </div>
            )}
            <button
              type="button"
              onClick={() => setIsCollapsed((value) => !value)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--sidebar-primary)] hover:text-[var(--sidebar-foreground)]"
              aria-label={isCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
            >
              {isCollapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
            </button>
          </div>

          {user && (
            <div className="flex items-center gap-2 px-3 py-2 text-xs border-b border-[var(--sidebar-border)]">
              {!isCollapsed && <span className="truncate text-[var(--text-secondary)]" title={user.display_name}>{user.display_name}</span>}
              <button type="button" onClick={() => setShowLogoutConfirm(true)} className="ml-auto text-[var(--text-tertiary)] hover:text-[var(--sidebar-foreground)]">
                {t('auth.logout')}
              </button>
            </div>
          )}

          <nav className="flex flex-1 flex-col gap-1 px-2 py-3">
            {navigationItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      'group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition',
                      isCollapsed ? 'justify-center' : '',
                      isActive
                        ? 'bg-[var(--sidebar-primary)] text-[var(--sidebar-primary-foreground)] shadow-[var(--shadow-toolbar)]'
                        : 'text-[var(--muted-foreground)] hover:bg-[var(--sidebar-primary)] hover:text-[var(--sidebar-foreground)]',
                    ].join(' ')
                  }
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon size={17} className="shrink-0" strokeWidth={1.7} />
                  {isCollapsed ? null : (
                    <span className="min-w-0">
                      <span className="block truncate font-medium leading-tight">{item.label}</span>
                      <span className="block truncate text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                        {item.description}
                      </span>
                    </span>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {!isCollapsed && (
            <div className="border-t border-[var(--sidebar-border)] px-3 py-3">
              <p className="text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {t('common.builtBy')}
              </p>
            </div>
          )}
          </div>
        </aside>

        <div className="flex h-screen min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-[var(--border)] bg-[var(--background)]/85 px-4 backdrop-blur-xl">
            <p className="truncate text-sm font-medium text-[var(--text)]">
              {pageTitle}
            </p>
            <div className="flex items-center gap-4">
              <p className="hidden truncate text-xs font-medium text-[var(--muted-foreground)] sm:block">
                {taskStatusSummary}
              </p>
              <LocaleSwitcher />
            </div>
          </header>

          <main
            className="flex w-full flex-1 flex-col overflow-hidden"
          >
            {children}
          </main>
        </div>
      </div>

      {showLogoutConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="bg-[var(--surface)] rounded-xl border border-[var(--border)] shadow-lg p-6 w-full max-w-xs mx-4">
            <p className="text-sm font-medium mb-2">{t('common.confirmLogout')}</p>
            <p className="text-xs text-[var(--text-secondary)] mb-4">{t('common.confirmLogoutMessage')}</p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setShowLogoutConfirm(false)}
                className="px-3 py-1.5 text-xs rounded-lg border border-[var(--border)] hover:bg-[var(--bg)]"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={() => { setShowLogoutConfirm(false); logout(); }}
                className="px-3 py-1.5 text-xs rounded-lg bg-[var(--danger)] text-[var(--destructive-foreground)] hover:opacity-90"
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
