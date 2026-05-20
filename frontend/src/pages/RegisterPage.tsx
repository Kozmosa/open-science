import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n';

export default function RegisterPage() {
  const t = useT();
  const { register } = useAuth();
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError(t('auth.passwordMismatch'));
      return;
    }
    setSubmitting(true);
    try {
      await register(username, displayName, password);
      setSuccess(true);
    } catch (err: any) {
      setError(err.message || t('auth.registerFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <div className="bg-[var(--surface)] p-8 rounded-xl shadow-sm border border-[var(--border)] text-center max-w-sm">
          <h1 className="text-lg font-semibold mb-4">{t('auth.registrationSubmitted')}</h1>
          <p className="text-sm text-[var(--text-secondary)]">{t('auth.pendingApproval')}</p>
          <Link to="/login" className="text-blue-600 text-sm hover:underline mt-4 inline-block">{t('auth.backToLogin')}</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <form onSubmit={handleSubmit} className="bg-[var(--surface)] p-8 rounded-xl shadow-sm border border-[var(--border)] w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">{t('auth.register')}</h1>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.username')}</label>
          <input className="px-3 py-2 border border-[var(--border)] rounded-lg text-sm" placeholder={t('auth.username')} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.displayName')}</label>
          <input className="px-3 py-2 border border-[var(--border)] rounded-lg text-sm" placeholder={t('auth.displayName')} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.password')}</label>
          <input type="password" className="px-3 py-2 border border-[var(--border)] rounded-lg text-sm" placeholder={t('auth.password')} value={password} onChange={(e) => setPassword(e.target.value)} />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</label>
          <input type="password" className="px-3 py-2 border border-[var(--border)] rounded-lg text-sm" placeholder={t('auth.confirmPassword')} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button type="submit" disabled={submitting || !username || !displayName || !password || !confirm} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">
            {submitting ? t('common.loading') : t('auth.register')}
          </button>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mt-4 text-center">
          {t('auth.loginLink')} <Link to="/login" className="text-blue-600 hover:underline">{t('auth.login')}</Link>
        </p>
      </form>
    </div>
  );
}
