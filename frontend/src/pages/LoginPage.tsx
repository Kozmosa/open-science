import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@features/auth';
import { useT } from '@/shared/i18n';
import { BrandMark, Button, Input } from '@design-system/primitives';

export default function LoginPage() {
  const t = useT();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const result = await login(username, password);
      if (result?.must_change_password) {
        navigate('/change-password');
      } else {
        navigate('/');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('auth.loginFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <form onSubmit={handleSubmit} className="bg-[var(--surface)] p-8 rounded-xl shadow-sm border border-[var(--border)] w-full max-w-sm">
        <BrandMark className="mb-6" />
        {error && <p className="mb-4 text-sm text-[var(--danger)]">{error}</p>}
        <div className="flex flex-col gap-4">
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.username')}</label>
          <Input
            placeholder={t('auth.username')}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <label className="text-xs text-[var(--text-secondary)]">{t('auth.password')}</label>
          <Input
            type="password"
            placeholder={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button
            type="submit"
            disabled={submitting || !username || !password}
          >
            {submitting ? t('common.loading') : t('auth.login')}
          </Button>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mt-4 text-center">
          <Link to="/register" className="text-[var(--info)] hover:underline">
            {t('auth.registerLink')}
          </Link>
        </p>
      </form>
    </div>
  );
}
