import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { login as apiLogin, register as apiRegister, refreshToken, logoutApi, getMe } from '@/shared/api/endpoints';
import { setAccessToken, getStoredRefreshToken, setStoredRefreshToken } from '@/shared/api/client';
import type { UserInfo } from '@/shared/types';

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<UserInfo>;
  register: (username: string, displayName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = getStoredRefreshToken();
    if (!stored) {
      // Sync external auth storage with React state; unavoidable setState in effect.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false);
      return;
    }
    refreshToken(stored)
      .then((res) => {
        setAccessToken(res.access_token);
        return getMe();
      })
      .then((u) => setUser(u))
      .catch(() => {
        setStoredRefreshToken(null);
        setAccessToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string): Promise<UserInfo> => {
    const res = await apiLogin({ username, password });
    setAccessToken(res.access_token);
    setStoredRefreshToken(res.refresh_token);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (username: string, displayName: string, password: string) => {
    await apiRegister({ username, display_name: displayName, password });
  }, []);

  const logout = useCallback(async () => {
    const stored = getStoredRefreshToken();
    if (stored) {
      try { await logoutApi(stored); } catch { /* ignore */ }
    }
    setStoredRefreshToken(null);
    setAccessToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
