import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function RegisterPage() {
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
      setError('Passwords do not match');
      return;
    }
    setSubmitting(true);
    try {
      await register(username, displayName, password);
      setSuccess(true);
    } catch (err: any) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="bg-white p-8 rounded-xl shadow-sm border text-center max-w-sm">
          <h1 className="text-lg font-semibold mb-4">Registration Submitted</h1>
          <p className="text-sm text-gray-500">Your account is pending admin approval. You will be able to log in once approved.</p>
          <Link to="/login" className="text-blue-600 text-sm hover:underline mt-4 inline-block">Back to Login</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-sm border w-full max-w-sm">
        <h1 className="text-xl font-semibold mb-6">Register</h1>
        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}
        <div className="flex flex-col gap-4">
          <input className="px-3 py-2 border rounded-lg text-sm" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <input className="px-3 py-2 border rounded-lg text-sm" placeholder="Display Name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <input type="password" className="px-3 py-2 border rounded-lg text-sm" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <input type="password" className="px-3 py-2 border rounded-lg text-sm" placeholder="Confirm Password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <button type="submit" disabled={submitting || !username || !displayName || !password || !confirm} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">
            {submitting ? 'Loading...' : 'Register'}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-4 text-center">
          Already have an account? <Link to="/login" className="text-blue-600 hover:underline">Log in</Link>
        </p>
      </form>
    </div>
  );
}
