import { api } from '@/shared/api/client';
import type { AccessTokenResponse, AuthTokenResponse, UserInfoResponse } from '@/generated/transport';
import { adaptAuthToken, adaptUser } from '../types';
import type { AccessToken, AuthToken, UserInfo } from '../types';
import type {
  ChangePasswordRequest,
  LoginRequest,
  RegisterRequest,
} from '@/generated/transport';

export const login = (payload: LoginRequest): Promise<AuthToken> =>
  api.post<AuthTokenResponse>('/auth/login', payload).then(adaptAuthToken);

export const register = (payload: RegisterRequest): Promise<{ message: string }> =>
  api.post('/auth/register', payload);

export const refreshToken = (refreshTokenValue: string): Promise<AccessToken> =>
  api.post<AccessTokenResponse>('/auth/refresh', { refresh_token: refreshTokenValue });

export const logoutApi = (refreshTokenValue: string): Promise<void> =>
  api.post('/auth/logout', { refresh_token: refreshTokenValue });

export const getMe = (): Promise<UserInfo> => api.get<UserInfoResponse>('/auth/me').then(adaptUser);

export const changePassword = (payload: ChangePasswordRequest): Promise<void> =>
  api.post('/auth/change-password', payload);
