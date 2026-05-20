import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { changePassword } from '../api';
import { useT } from '../i18n';

export default function ChangePasswordPage() {
  const t = useT();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

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
    } catch (err: any) {
      setError(err.message || t('auth.changePasswordFailed'));
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
        {error && <p className="text-sm text-red-500 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.currentPassword')}</span>
            <input
              type="password"
              className="px-3 py-2 rounded-lg text-sm bg-[var(--bg)] border border-[var(--border)]"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoFocus
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.newPassword')}</span>
            <input
              type="password"
              className="px-3 py-2 rounded-lg text-sm bg-[var(--bg)] border border-[var(--border)]"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</span>
            <input
              type="password"
              className="px-3 py-2 rounded-lg text-sm bg-[var(--bg)] border border-[var(--border)]"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={submitting || !oldPassword || !newPassword || !confirm}
            className="px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50 hover:bg-blue-700 transition-colors"
          >
            {submitting ? t('common.loading') : t('auth.changePassword')}
          </button>
        </div>
      </form>
    </div>
  );
}
