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

export function AccountMenu({ user, onLogout }: { user: UserInfo; onLogout: () => void }) {
  const t = useT();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label={t('layout.accountMenu')}>
          <UserRound aria-hidden="true" size={17} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
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
