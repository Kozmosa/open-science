import { Menu, Search } from 'lucide-react';
import { Button } from '@design-system';
import type { UserInfo } from '@/shared/types';
import { useT } from '@/shared/i18n';
import LocaleSwitcher from '@/components/common/LocaleSwitcher';
import { AccountMenu } from './AccountMenu';

interface TopBarProps {
  user: UserInfo;
  taskStatusSummary: string | null;
  onOpenNavigation: () => void;
  onOpenCommandPalette: () => void;
  onLogout: () => void;
}

export function TopBar({ user, taskStatusSummary, onOpenNavigation, onOpenCommandPalette, onLogout }: TopBarProps) {
  const t = useT();
  return (
    <header className="sticky top-0 z-40 flex h-12 shrink-0 items-center justify-between border-b border-[var(--osci-color-border)] bg-[var(--osci-topbar-background-translucent)] px-3 backdrop-blur-[16px] md:px-5 [backdrop-filter:var(--osci-topbar-backdrop-filter)]">
      <div className="flex items-center gap-2">
        <Button size="icon-sm" variant="ghost" aria-label={t('layout.openNavigation')} onClick={onOpenNavigation} className="md:hidden">
          <Menu aria-hidden="true" size={17} />
        </Button>
        <Button variant="secondary" size="sm" onClick={onOpenCommandPalette} aria-label={t('layout.openCommandPalette')} className="gap-2">
          <Search aria-hidden="true" size={15} />
          <span className="hidden sm:inline">{t('layout.commandPlaceholder')}</span>
          <kbd className="hidden rounded border border-[var(--osci-color-border)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--osci-color-text-muted)] lg:inline">Ctrl/⌘+Shift+P</kbd>
        </Button>
      </div>
      <div className="flex items-center gap-2">
        {taskStatusSummary ? <p className="hidden max-w-80 truncate text-xs font-medium text-[var(--osci-color-text-secondary)] lg:block">{taskStatusSummary}</p> : null}
        <LocaleSwitcher />
        <div className="md:hidden"><AccountMenu user={user} onLogout={onLogout} /></div>
      </div>
    </header>
  );
}
