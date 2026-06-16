import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { getAdminUsers, updateAdminUser, resetUserPassword } from '@/shared/api';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';
import { queryKeys } from '@/shared/api/queryKeys';

/** Format an ISO-8601 timestamp as a human-readable relative time string. */
function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return 'Just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

export function UsersTab() {
  const t = useT();
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.admin.users,
    queryFn: getAdminUsers,
    enabled: currentUser?.role === 'admin',
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      updateAdminUser(id, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.users }),
  });

  const resetMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      resetUserPassword(id, { password }),
    onSuccess: () => { setResetUserId(null); setNewPassword(''); },
  });

  if (currentUser?.role !== 'admin') return null;
  if (isLoading) return <p className="p-4 text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>;

  const users = data?.items ?? [];

  const getStatusCardClasses = (status: string) => {
    switch (status) {
      case 'pending':
        return 'bg-amber-500/5 border-amber-500/20';
      case 'active':
        return 'bg-emerald-500/5 border-emerald-500/20';
      default:
        return 'bg-[var(--bg-secondary)] border-[var(--border)]';
    }
  };

  const getStatusBadgeClasses = (status: string) => {
    switch (status) {
      case 'pending':
        return 'bg-amber-500/10 text-amber-600';
      case 'active':
        return 'bg-emerald-500/10 text-emerald-600';
      default:
        return 'bg-[var(--bg)] text-[var(--text-secondary)]';
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--text)]">{t('pages.settings.users.title')}</h3>
        <span className="text-xs text-[var(--text-secondary)]">{t('pages.settings.users.count', { count: users.length })}</span>
      </div>
      {users.map((u) => (
        <div key={u.id} className={`flex items-center justify-between p-3 rounded-lg border text-sm ${getStatusCardClasses(u.status)}`}>
          <div className="flex flex-col gap-0.5 min-w-0">
            <div className="flex items-center flex-wrap gap-x-2 gap-y-0.5">
              <span className="font-medium text-[var(--text)]">{u.username}</span>
              <span className="text-[var(--text-tertiary)]">{u.display_name}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded ${getStatusBadgeClasses(u.status)}`}>{u.status}</span>
              {u.role === 'admin' && <span className="text-xs bg-[var(--apple-blue)]/10 text-[var(--apple-blue)] px-1.5 py-0.5 rounded">admin</span>}
              <span className="inline-flex items-center gap-1">
                <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${u.is_online ? 'bg-emerald-500' : 'bg-gray-400'}`} />
                <span className="text-xs text-[var(--text-tertiary)]">{u.is_online ? t('pages.settings.users.online') : t('pages.settings.users.offline')}</span>
              </span>
            </div>
            <div className="text-xs text-[var(--text-tertiary)]">
              {t('pages.settings.users.lastLogin')}{' '}
              {u.last_login_at ? formatRelativeTime(u.last_login_at) : t('pages.settings.users.never')}
            </div>
          </div>
          <div className="flex gap-2 flex-shrink-0">
            {u.status === 'pending' && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'active' })}
                className="text-xs px-2 py-1 bg-[var(--apple-green)] text-white rounded hover:bg-[var(--apple-green)]/90">{t('pages.settings.users.approve')}</button>
            )}
            {u.status === 'active' && u.id !== currentUser.id && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'disabled' })}
                className="text-xs px-2 py-1 bg-[var(--bg-secondary)] text-[var(--text)] rounded hover:bg-[var(--bg)] border border-[var(--border)]">{t('pages.settings.users.disable')}</button>
            )}
            {u.status === 'disabled' && (
              <button type="button" onClick={() => updateMutation.mutate({ id: u.id, status: 'active' })}
                className="text-xs px-2 py-1 bg-[var(--apple-green)] text-white rounded hover:bg-[var(--apple-green)]/90">{t('pages.settings.users.reEnable')}</button>
            )}
            {u.id !== currentUser.id && (
              <button type="button" onClick={() => setResetUserId(resetUserId === u.id ? null : u.id)}
                className="text-xs px-2 py-1 bg-[var(--bg-secondary)] text-[var(--text)] rounded hover:bg-[var(--bg)] border border-[var(--border)]">{t('pages.settings.users.resetPassword')}</button>
            )}
          </div>
        </div>
      ))}
      {resetUserId && (
        <div className="flex gap-2 items-center p-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)]">
          <span className="text-xs text-[var(--text-secondary)]">{t('pages.settings.users.newPassword')}</span>
          <input
            type="text"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder={t('pages.settings.users.enterNewPassword')}
            className="text-xs px-2 py-1 border border-[var(--border)] rounded flex-1 bg-[var(--surface)] text-[var(--text)]"
          />
          <button
            type="button"
            onClick={() => resetMutation.mutate({ id: resetUserId, password: newPassword })}
            disabled={!newPassword}
            className="text-xs px-2 py-1 bg-[var(--apple-blue)] text-white rounded disabled:opacity-50"
          >{t('pages.settings.users.set')}</button>
        </div>
      )}
    </div>
  );
}
