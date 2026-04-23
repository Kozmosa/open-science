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
  const asideWidth = useMemo(() => (isCollapsed ? 'w-[72px]' : 'w-[260px]'), [isCollapsed]);
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
    <div className="min-h-screen bg-[var(--bg-secondary)] text-[var(--text)]">
      <div className="flex min-h-screen">
        <aside
          className={`${asideWidth} flex shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] transition-all duration-300 ease-out`}
        >
          {/* Sidebar header */}
          <div className="flex items-center justify-between px-4 py-3">
            {!isCollapsed && (
              <div className="min-w-0">
                <p
                  className="truncate text-[21px] font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
                  style={{ fontFamily: 'var(--font-display)' }}
                >
                  {t('common.appName')}
                </p>
              </div>
            )}
            <button
              type="button"
              onClick={() => setIsCollapsed((value) => !value)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--text-tertiary)] transition hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]"
              aria-label={isCollapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
            >
              {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex flex-1 flex-col gap-1 px-3 py-2">
            {navigationItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      'group flex items-center gap-3 rounded-lg px-3 py-2.5 transition',
                      isCollapsed ? 'justify-center' : '',
                      isActive
                        ? 'bg-[var(--apple-blue)] text-white'
                        : 'text-[var(--text-secondary)] hover:bg-[var(--bg-secondary)] hover:text-[var(--text)]',
                    ].join(' ')
                  }
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon size={18} className="shrink-0" strokeWidth={1.5} />
                  {isCollapsed ? null : (
                    <span className="min-w-0">
                      <span className="block text-sm font-medium leading-tight tracking-[-0.224px]">
                        {item.label}
                      </span>
                      <span className="block text-xs leading-relaxed text-[var(--text-tertiary)] tracking-[-0.12px]">
                        {item.description}
                      </span>
                    </span>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Sidebar footer */}
          {!isCollapsed && (
            <div className="border-t border-[var(--border)] px-4 py-3">
              <p className="text-xs leading-relaxed tracking-[-0.12px] text-[var(--text-tertiary)]">
                {t('layout.brandLine')}
              </p>
            </div>
          )}
        </aside>

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          {/* Top navigation bar — Apple glass style */}
          <header
            className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-[var(--border)] px-6"
            style={{
              background: 'rgba(0, 0, 0, 0.72)',
              backdropFilter: 'saturate(180%) blur(20px)',
              WebkitBackdropFilter: 'saturate(180%) blur(20px)',
            }}
          >
            <div className="flex items-center gap-4">
              <p className="text-xs font-medium uppercase tracking-wide text-white/80">
                {t('layout.headerEyebrow')}
              </p>
              <span className="h-3 w-px bg-white/20" />
              <p className="text-xs text-white/60">
                {t('layout.headerDescription')}
              </p>
            </div>
            <LocaleSwitcher />
          </header>

          <main className="mx-auto flex w-full max-w-[1100px] flex-1 flex-col px-6 py-8">
            {children}
          </main>

          <footer className="border-t border-[var(--border)] px-6 py-4">
            <div className="mx-auto flex w-full max-w-[1100px] items-center justify-between">
              <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                {t('layout.footerDescription')}
              </p>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
}

export default Layout;
