import { useCallback, useState } from 'react';
import { Button, Dialog, Input } from '@design-system';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';
import { changePassword } from '@/shared/api';

export function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const { logout } = useAuth();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleClose = useCallback(() => {
    setOldPassword('');
    setNewPassword('');
    setConfirm('');
    setError('');
    onClose();
  }, [onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (newPassword !== confirm) {
      setError(t('auth.passwordMismatch'));
      return;
    }
    if (newPassword.length < 4) {
      setError(t('auth.passwordTooShort'));
      return;
    }
    setSubmitting(true);
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      await logout();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t('auth.changePasswordFailed'));
      setSubmitting(false);
    }
  };

  return (
    <Dialog isOpen={open} onClose={handleClose} title={t('auth.changePassword')} size="sm">
      <form onSubmit={handleSubmit}>
        {error && <p className="mb-3 text-sm text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.currentPassword')}</span>
            <Input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoFocus
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.newPassword')}</span>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</span>
            <Input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </label>
          <div className="flex gap-2 justify-end mt-2">
            <Button type="button" variant="secondary" onClick={handleClose}>{t('common.cancel')}</Button>
            <Button type="submit" disabled={submitting || !oldPassword || !newPassword || !confirm}>
              {submitting ? t('common.loading') : t('auth.changePassword')}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}
