import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getEnvironments, getEnvAccess, grantEnvAccess, revokeEnvAccess, getAdminUsers } from '@/shared/api';
import { useAuth } from '@features/auth';
import { useT } from '@/shared/i18n';
import { Select } from '@design-system/primitives';
import { AccessGrantPanel } from '../../components/settings/AccessGrantPanel';
import { AccessItemRow } from '../../components/settings/AccessItemRow';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import { queryKeys } from '@/shared/api/queryKeys';

export function EnvAccessTab() {
  const { user } = useAuth();
  const t = useT();
  const queryClient = useQueryClient();
  const [selectedEnv, setSelectedEnv] = useState<string | null>(null);
  const [grantUserId, setGrantUserId] = useState('');
  const [maxTasks, setMaxTasks] = useState('');

  const { data: envs, isLoading: envsLoading } = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: () => getEnvironments(),
    enabled: user?.role === 'admin',
  });

  const { data: users } = useQuery({
    queryKey: queryKeys.admin.users,
    queryFn: getAdminUsers,
    enabled: user?.role === 'admin',
  });

  const { data: accessData, isLoading: accessLoading } = useQuery({
    queryKey: queryKeys.envAccess.byEnv(selectedEnv),
    queryFn: () => getEnvAccess(selectedEnv!),
    enabled: !!selectedEnv && user?.role === 'admin',
  });

  const grantMutation = useMutation({
    mutationFn: () =>
      grantEnvAccess(selectedEnv!, {
        user_id: grantUserId,
        max_concurrent_tasks: maxTasks ? parseInt(maxTasks) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.envAccess.byEnv(selectedEnv) });
      setGrantUserId('');
      setMaxTasks('');
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (userId: string) => revokeEnvAccess(selectedEnv!, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.envAccess.byEnv(selectedEnv) }),
  });

  if (user?.role !== 'admin') return null;

  const envList = envs?.items ?? [];
  const accessItems = accessData?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">{t('pages.settings.tabs.envAccess')}</h3>

      <Select value={selectedEnv ?? ''} onChange={(e) => setSelectedEnv(e.target.value || null)}>
        <option value="">{t('pages.settings.envAccess.selectEnv')}</option>
        {envList.map((e) => (
          <option key={e.id} value={e.id}>
            {e.display_name || e.alias}
          </option>
        ))}
      </Select>

      {envsLoading && (
        <LoadingSpinner size="sm" />
      )}

      {!envsLoading && !selectedEnv && (
        <p className="text-sm text-[var(--text-secondary)]">{t('pages.settings.envAccess.noEnvSelected')}</p>
      )}

      {selectedEnv && accessLoading && (
        <LoadingSpinner size="sm" />
      )}

      {selectedEnv && !accessLoading && (
        <div className="flex flex-col gap-2">
          {accessItems.length === 0 && (
            <p className="text-sm text-[var(--text-secondary)]">{t('pages.settings.envAccess.noAccess')}</p>
          )}

          {accessItems.map((a) => (
            <AccessItemRow
              key={a.user_id}
              label={a.username}
              sublabel={a.display_name}
              meta={`${t('pages.settings.envAccess.maxTasks')}: ${a.max_concurrent_tasks ?? t('pages.settings.envAccess.unlimited')}`}
              onRemove={() => revokeMutation.mutate(a.user_id)}
              removeLabel={t('pages.settings.envAccess.remove')}
              disabled={revokeMutation.isPending}
            />
          ))}

          {revokeMutation.isError && (
            <p className="text-xs text-[var(--destructive)]">
              {(revokeMutation.error as Error)?.message ?? 'Request failed'}
            </p>
          )}

          <AccessGrantPanel
            users={users?.items ?? []}
            selectedUserId={grantUserId}
            onUserChange={setGrantUserId}
            onGrant={() => grantMutation.mutate()}
            grantLabel={t('pages.settings.envAccess.grant')}
            userPlaceholder={t('pages.settings.envAccess.grantTo')}
            disabled={grantMutation.isPending}
            extraField={
              <input
                value={maxTasks}
                onChange={(e) => setMaxTasks(e.target.value)}
                placeholder={t('pages.settings.envAccess.maxTasks')}
                className="w-20 text-xs px-2 py-1.5 rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]"
              />
            }
          />

          {grantMutation.isError && (
            <p className="text-xs text-[var(--destructive)]">
              {(grantMutation.error as Error)?.message ?? 'Request failed'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
