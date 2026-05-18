import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n';

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
      await login(username, password);
      navigate('/');
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-sm border w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">AINRF</h1>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <input
            className="px-3 py-2 border rounded-lg text-sm"
            placeholder={t('auth.username')}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
          <input
            type="password"
            className="px-3 py-2 border rounded-lg text-sm"
            placeholder={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"
          >
            {submitting ? 'Loading...' : t('auth.login')}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-4 text-center">
          <Link to="/register" className="text-blue-600 hover:underline">
            {t('auth.registerLink')}
          </Link>
        </p>
      </form>
    </div>
  );
}
