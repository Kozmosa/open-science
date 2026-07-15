import { LogOut, UserRound } from 'lucide-react';
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@design-system';
import type { UserInfo } from '@/shared/types';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';

interface AccountMenuProps {
  user: UserInfo;
  onLogout: () => void;
  showIdentity?: boolean;
  align?: 'start' | 'center' | 'end';
}

export function AccountMenu({ user, onLogout, showIdentity = false, align = 'end' }: AccountMenuProps) {
  const t = useT();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size={showIdentity ? 'md' : 'icon-sm'}
          variant="ghost"
          aria-label={t('layout.accountMenu')}
          className={cn(showIdentity && 'w-full justify-start gap-2 px-2.5')}
        >
          <UserRound aria-hidden="true" className="shrink-0" size={17} />
          {showIdentity ? <span className="min-w-0 truncate">{user.display_name}</span> : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-56">
        <DropdownMenuLabel>
          <span className="block truncate text-sm text-[var(--osci-color-text)]">{user.display_name}</span>
          <span className="block truncate font-normal text-[var(--osci-color-text-muted)]">@{user.username}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onLogout} className="text-[var(--osci-color-danger)]">
          <LogOut aria-hidden="true" className="mr-2" size={15} />
          {t('auth.logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
