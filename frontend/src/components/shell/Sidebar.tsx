import { ChevronLeft, ChevronRight } from 'lucide-react';
import { BrandMark, Button } from '@design-system';
import type { ResolvedAppRoute } from '@/app/routeRegistry';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';
import type { UserInfo } from '@/shared/types';
import { AccountMenu } from './AccountMenu';
import { NavigationLinks } from './NavigationLinks';

interface SidebarProps {
  routes: ResolvedAppRoute[];
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  user: UserInfo;
  onLogout: () => void;
}

export function Sidebar({ routes, collapsed, onCollapsedChange, user, onLogout }: SidebarProps) {
  const t = useT();
  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-screen shrink-0 overflow-hidden border-r border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] text-[var(--osci-color-text)] transition-[width] duration-200 md:flex md:flex-col',
        collapsed ? 'w-[var(--osci-sidebar-collapsed-width)]' : 'w-[var(--osci-sidebar-expanded-width)]',
      )}
    >
      <div className="flex h-12 items-center gap-2 border-b border-[var(--osci-color-border)] px-2.5">
        <BrandMark showName={false} className="h-7 w-7 shrink-0" />
        {collapsed ? null : <span className="min-w-0 flex-1 truncate text-sm font-semibold">{t('common.appName')}</span>}
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={collapsed ? t('layout.expandSidebar') : t('layout.collapseSidebar')}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          {collapsed ? <ChevronRight aria-hidden="true" size={15} /> : <ChevronLeft aria-hidden="true" size={15} />}
        </Button>
      </div>
      <NavigationLinks routes={routes} collapsed={collapsed} />
      <div className="border-t border-[var(--osci-color-border)] p-2">
        <AccountMenu user={user} onLogout={onLogout} showIdentity={!collapsed} align="start" />
      </div>
      {collapsed ? null : (
        <p className="px-3 pb-3 text-[11px] leading-relaxed text-[var(--osci-color-text-muted)]">
          {t('common.builtBy')}
        </p>
      )}
    </aside>
  );
}
