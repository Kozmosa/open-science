import type { AccessTokenResponse, AuthTokenResponse, UserInfoResponse } from '@/generated/transport';

export type UserInfo = UserInfoResponse;
export type AuthToken = AuthTokenResponse & { user: UserInfo };
export type AccessToken = AccessTokenResponse;

export function adaptAuthToken(value: AuthTokenResponse): AuthToken {
  return { access_token: value.access_token, refresh_token: value.refresh_token, user: value.user };
}

export function adaptUser(value: UserInfoResponse): UserInfo {
  return value;
}
