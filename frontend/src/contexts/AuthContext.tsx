import { createContext, useContext, type ReactNode } from 'react';

export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
  role: string;
  status: string;
}

interface AuthContextValue {
  user: AuthUser | null;
}

const AuthContext = createContext<AuthContextValue>({ user: null });

export function AuthProvider({ children }: { children: ReactNode }) {
  return <AuthContext.Provider value={{ user: null }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
