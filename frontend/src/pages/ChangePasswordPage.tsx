import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@features/auth';
import { changePassword } from '@/shared/api';
import { useT } from '@/shared/i18n';
import { Button, Input } from '@design-system';

export default function ChangePasswordPage() {
  const t = useT();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const errorId = 'change-password-form-error';

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
      // Force re-login with new password to refresh the session state
      await logout();
      navigate('/login');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('auth.changePasswordFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <form
        onSubmit={handleSubmit}
        className="bg-[var(--surface)] p-8 rounded-2xl border border-[var(--border)] shadow-sm w-full max-w-sm"
      >
        <h1 className="text-xl font-semibold mb-2 text-center">{t('auth.changePassword')}</h1>
        <p className="text-xs text-[var(--text-secondary)] text-center mb-6">
          {t('auth.mustChangePassword')}
        </p>
        {error && <p id={errorId} role="alert" className="mb-4 text-sm text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-4">
          <label htmlFor="current-password" className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.currentPassword')}</span>
            <Input
              id="current-password"
              name="current_password"
              type="password"
              autoComplete="current-password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              aria-describedby={error ? errorId : undefined}
              aria-invalid={error ? true : undefined}
              autoFocus
            />
          </label>
          <label htmlFor="new-password" className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.newPassword')}</span>
            <Input
              id="new-password"
              name="new_password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              aria-describedby={error ? errorId : undefined}
              aria-invalid={error ? true : undefined}
            />
          </label>
          <label htmlFor="new-password-confirmation" className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</span>
            <Input
              id="new-password-confirmation"
              name="new_password_confirmation"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-describedby={error ? errorId : undefined}
              aria-invalid={error ? true : undefined}
            />
          </label>
          <Button
            type="submit"
            disabled={submitting || !oldPassword || !newPassword || !confirm}
          >
            {submitting ? t('common.loading') : t('auth.changePassword')}
          </Button>
        </div>
      </form>
    </div>
  );
}
