import { NavLink } from 'react-router-dom';
import type { ResolvedAppRoute } from '@/app/routeRegistry';
import { cn } from '@/shared/utils/cn';

interface NavigationLinksProps {
  routes: ResolvedAppRoute[];
  collapsed?: boolean;
  onNavigate?: () => void;
}

export function NavigationLinks({ routes, collapsed = false, onNavigate }: NavigationLinksProps) {
  return (
    <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 px-2 py-3">
      {routes.map((route) => {
        const Icon = route.icon;
        return (
          <NavLink
            key={route.id}
            to={route.path}
            onClick={onNavigate}
            aria-label={collapsed ? route.label : undefined}
            title={collapsed ? route.label : undefined}
            className={({ isActive }) => cn(
              'group flex min-h-10 items-center gap-3 rounded-[var(--osci-radius-sm)] px-2.5 py-2 text-sm font-medium transition',
              collapsed && 'justify-center',
              isActive
                ? 'bg-[var(--osci-color-primary-soft)] text-[var(--osci-color-primary)]'
                : 'text-[var(--osci-color-text-secondary)] hover:bg-[var(--osci-color-surface-subtle)] hover:text-[var(--osci-color-text)]',
            )}
          >
            <Icon aria-hidden="true" className="shrink-0" size={18} strokeWidth={1.7} />
            {collapsed ? null : (
              <span className="min-w-0">
                <span className="block truncate leading-tight">{route.label}</span>
                <span className="block truncate text-[11px] leading-relaxed text-[var(--osci-color-text-muted)]">
                  {route.description}
                </span>
              </span>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}
