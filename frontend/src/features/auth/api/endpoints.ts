import { api } from '@/shared/api/client';
import type { AccessTokenResponse, AuthTokenResponse, UserInfo } from '@/shared/types';
import type {
  ChangePasswordRequest,
  LoginRequest,
  RegisterRequest,
} from '@/shared/api/transportTypes';

export const login = (payload: LoginRequest): Promise<AuthTokenResponse> =>
  api.post('/auth/login', payload);

export const register = (payload: RegisterRequest): Promise<{ message: string }> =>
  api.post('/auth/register', payload);

export const refreshToken = (refreshTokenValue: string): Promise<AccessTokenResponse> =>
  api.post('/auth/refresh', { refresh_token: refreshTokenValue });

export const logoutApi = (refreshTokenValue: string): Promise<void> =>
  api.post('/auth/logout', { refresh_token: refreshTokenValue });

export const getMe = (): Promise<UserInfo> => api.get('/auth/me');

export const changePassword = (payload: ChangePasswordRequest): Promise<void> =>
  api.post('/auth/change-password', payload);
