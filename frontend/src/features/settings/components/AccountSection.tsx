import { Button, SectionCard, SectionHeader } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';

export interface AccountSectionProps {
  onPasswordClick: () => void;
}

export function AccountSection({ onPasswordClick }: AccountSectionProps) {
  const t = useT();
  const { user } = useAuth();

  return (
    <SectionCard
      header={
        <SectionHeader
          title={t('pages.settings.account.title')}
          description={t('pages.settings.account.description')}
        />
      }
    >
      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[var(--text)]">{user?.display_name ?? user?.username}</p>
            <p className="text-xs text-[var(--text-secondary)]">{user?.username} · {user?.role}</p>
          </div>
          <Button variant="secondary" onClick={onPasswordClick}>
            {t('auth.changePassword')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
