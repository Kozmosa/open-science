import {
  Boxes,
  ChevronLeft,
  ChevronRight,
  FolderKanban,
  ListChecks,
  Settings,
  SquareTerminal,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';
import { NavLink } from 'react-router-dom';
import LocaleSwitcher from './LocaleSwitcher';
import { useT } from '../../i18n';

interface Props {
  children: ReactNode;
}

interface NavigationItem {
  label: string;
  to: string;
  description: string;
  icon: typeof SquareTerminal;
}

function Layout({ children }: Props) {
  const t = useT();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const asideWidth = useMemo(() => (isCollapsed ? 'w-20' : 'w-72'), [isCollapsed]);
  const navigationItems: NavigationItem[] = [
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
      label: t('navigation.containers.label'),
      to: '/containers',
      description: t('navigation.containers.description'),
      icon: Boxes,
    },
    {
      label: t('navigation.settings.label'),
      to: '/settings',
      description: t('navigation.settings.description'),
      icon: Settings,
    },
  ];

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      <div className="flex min-h-screen">
        <aside
          className={`${asideWidth} flex shrink-0 flex-col border-r border-gray-200 bg-white/95 px-3 py-4 shadow-sm transition-all duration-200`}
        >
          <div className="flex items-start justify-between gap-3 px-2">
            <div className={isCollapsed ? 'hidden' : 'block'}>
              <p className="text-lg font-semibold text-[var(--accent)]">{t('common.appName')}</p>
              <p className="mt-1 text-sm text-gray-600">{t('layout.brandLine')}</p>
            </div>
            <button
              type="button"
              onClick={() => setIsCollapsed((value) => !value)}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-600 transition hover:border-[var(--accent)]/30 hover:text-[var(--accent)]"
              aria-label={isCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
            >
              {isCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </button>
          </div>

          <nav className="mt-6 flex flex-1 flex-col gap-2">
            {navigationItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      'group flex items-center gap-3 rounded-2xl border px-3 py-3 transition',
                      isCollapsed ? 'justify-center' : '',
                      isActive
                        ? 'border-[var(--accent)]/20 bg-[var(--accent)]/10 text-[var(--accent)] shadow-sm'
                        : 'border-transparent text-gray-600 hover:border-gray-200 hover:bg-gray-100 hover:text-gray-900',
                    ].join(' ')
                  }
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon size={18} className="shrink-0" />
                  {isCollapsed ? null : (
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{item.label}</span>
                      <span className="block text-xs text-gray-500">{item.description}</span>
                    </span>
                  )}
                </NavLink>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <header className="border-b border-gray-200 bg-white/80 px-4 py-4 backdrop-blur sm:px-6 lg:px-8">
            <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-6">
              <div>
                <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
                  {t('layout.headerEyebrow')}
                </p>
                <p className="mt-1 text-sm text-gray-600">{t('layout.headerDescription')}</p>
              </div>
              <LocaleSwitcher />
            </div>
          </header>

          <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col">{children}</main>

          <footer className="border-t border-gray-200 bg-white/80 px-4 py-4 text-sm text-gray-500 sm:px-6 lg:px-8">
            <div className="mx-auto w-full max-w-6xl">
              {t('layout.footerDescription')}
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}

export default Layout;
