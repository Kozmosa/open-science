import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@features/auth';
import { useT } from '@/shared/i18n';
import { Button, Input } from '@design-system/primitives';

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
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('auth.registerFailed'));
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
          <Link to="/login" className="mt-4 inline-block text-sm text-[var(--info)] hover:underline">{t('auth.backToLogin')}</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <form onSubmit={handleSubmit} className="bg-[var(--surface)] p-8 rounded-xl shadow-sm border border-[var(--border)] w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">{t('auth.register')}</h1>
        {error && <p className="mb-4 text-sm text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.username')} <span className="text-[var(--text-tertiary)]">({t('auth.usernameHint')})</span></label>
          <Input placeholder={t('auth.username')} value={username} onChange={(e) => setUsername(e.target.value.replace(/[^a-z0-9_-]/g, '').slice(0, 31))} autoFocus />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.displayName')}</label>
          <Input placeholder={t('auth.displayName')} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.password')}</label>
          <Input type="password" placeholder={t('auth.password')} value={password} onChange={(e) => setPassword(e.target.value)} />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.confirmPassword')}</label>
          <Input type="password" placeholder={t('auth.confirmPassword')} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <Button type="submit" disabled={submitting || !username || !displayName || !password || !confirm}>
            {submitting ? t('common.loading') : t('auth.register')}
          </Button>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mt-4 text-center">
          {t('auth.loginLink')} <Link to="/login" className="text-[var(--info)] hover:underline">{t('auth.login')}</Link>
        </p>
      </form>
    </div>
  );
}
