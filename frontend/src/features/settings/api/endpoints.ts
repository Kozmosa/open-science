import { api } from '@/shared/api/client';
import type {
  AdminUserItem,
  AdminUserListResponse,
  CodexDefaults,
  DeploymentVersionResponse,
  MonitoringSettingsResponse,
  SearchSettingsResponse,
  SkillDetail,
  SkillImportInput,
  SkillImportResponse,
  SkillListResponse,
  SkillRegistryInstallResponse,
  SkillRegistryListResponse,
  SkillRegistryStatus,
  SkillRegistryUpdateResponse,
  EnvAccessItem,
  EnvAccessListResponse,
} from '../types';
import {
  adaptSkillDetail,
  adaptSkillList,
  adaptSkillRegistries,
  adaptSkillRegistryStatus,
  toSkillImportRequest,
} from '../types';
import type {
  AdminUserListResponse as TransportAdminUserListResponse,
  AdminUserResponse as TransportAdminUserResponse,
  CodexDefaultsResponse,
  DeploymentVersionResponse as TransportDeploymentVersionResponse,
  EnvironmentAccessListResponse,
  SkillDetailResponse,
  SkillListResponse as TransportSkillListResponse,
  SkillRegistryListResponse as TransportSkillRegistryListResponse,
  SkillRegistryStatusResponse,
} from '@/generated/transport';
import type {
  AdminPasswordResetRequest,
  AdminUserUpdateRequest,
  EnvironmentAccessRequest,
  SearchSettingsUpdateRequest,
  SkillRegistryUpdateRequest,
} from '@/generated/transport';

export const getSkills = (): Promise<SkillListResponse> => api.get<TransportSkillListResponse>('/skills').then(adaptSkillList);
export const getSkillDetail = (skillId: string): Promise<SkillDetail> =>
  api.get<SkillDetailResponse>(`/skills/${skillId}`).then(adaptSkillDetail);
export const importSkill = (payload: SkillImportInput): Promise<SkillImportResponse> =>
  api.post('/skills/import', toSkillImportRequest(payload));

export const getCodexDefaults = (): Promise<CodexDefaults> =>
  api.get<CodexDefaultsResponse>('/settings/codex-defaults');
export const getDeploymentVersion = (): Promise<DeploymentVersionResponse> =>
  api.get<TransportDeploymentVersionResponse>('/settings/deployment-version');
export const getFrontendBuildVersion = (): Promise<DeploymentVersionResponse> =>
  fetch('/build-info.json', { headers: { Accept: 'application/json' } })
    .then((response) => response.ok
      ? response.json() as Promise<DeploymentVersionResponse>
      : { short_commit: null, committed_at: null })
    .catch(() => ({ short_commit: null, committed_at: null }));

export const getSkillRegistries = (): Promise<SkillRegistryListResponse> =>
  api.get<TransportSkillRegistryListResponse>('/skill-registries').then(adaptSkillRegistries);
export const getSkillRegistryStatus = (registryId: string): Promise<SkillRegistryStatus> =>
  api.get<SkillRegistryStatusResponse>(`/skill-registries/${registryId}/status`).then(adaptSkillRegistryStatus);
export const installSkillRegistry = (registryId: string): Promise<SkillRegistryInstallResponse> =>
  api.post(`/skill-registries/${registryId}/install`, {});
export const updateSkillRegistry = (
  registryId: string,
  payload: SkillRegistryUpdateRequest,
): Promise<SkillRegistryUpdateResponse> =>
  api.post(`/skill-registries/${registryId}/update`, payload);

export const getSearchSettings = (): Promise<SearchSettingsResponse> => api.get('/settings/search');
export const updateSearchSettings = (
  payload: SearchSettingsUpdateRequest,
): Promise<SearchSettingsResponse> => api.patch('/settings/search', payload);
export const getMonitoringSettings = (): Promise<MonitoringSettingsResponse> =>
  api.get('/settings/monitoring');

export const getAdminUsers = (): Promise<AdminUserListResponse> => api.get<TransportAdminUserListResponse>('/admin/users');
export const updateAdminUser = (
  userId: string,
  payload: AdminUserUpdateRequest,
): Promise<AdminUserItem> => api.patch<TransportAdminUserResponse>(`/admin/users/${userId}`, payload);
export const resetUserPassword = (
  userId: string,
  payload: AdminPasswordResetRequest,
): Promise<void> => api.put(`/admin/users/${userId}/password`, payload);
export const getEnvAccess = (environmentId: string): Promise<EnvAccessListResponse> =>
  api.get<EnvironmentAccessListResponse>(`/admin/environments/${environmentId}/access`);
export const grantEnvAccess = (
  environmentId: string,
  payload: EnvironmentAccessRequest,
): Promise<EnvAccessItem> => api.put(`/admin/environments/${environmentId}/access`, payload);
export const revokeEnvAccess = (environmentId: string, userId: string): Promise<void> =>
  api.delete(`/admin/environments/${environmentId}/access/${userId}`);
