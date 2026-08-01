import { api } from '@/shared/api/client';
import type {
  AdminUserItem,
  AdminUserListResponse,
  CodexDefaults,
  DeploymentVersionResponse,
  MonitoringSettingsResponse,
  SearchSettingsResponse,
  SkillDetail,
  SkillImportResponse,
  SkillListResponse,
  SkillPreview,
  SkillRegistryInstallResponse,
  SkillRegistryListResponse,
  SkillRegistryStatus,
  SkillRegistryUpdateResponse,
  EnvAccessItem,
  EnvAccessListResponse,
} from '@/shared/types';
import type {
  AdminPasswordResetRequest,
  AdminUserUpdateRequest,
  EnvAccessRequest,
  SearchSettingsUpdateRequest,
  SkillImportRequest,
  SkillRegistryUpdateRequest,
} from '@/shared/api/transportTypes';

export const getSkills = (): Promise<SkillListResponse> => api.get('/skills');
export const getSkillDetail = (skillId: string): Promise<SkillDetail> =>
  api.get(`/skills/${skillId}`);
export const previewSkillSettings = (skillId: string): Promise<SkillPreview> =>
  api.get(`/skills/${skillId}/preview`);
export const importSkill = (payload: SkillImportRequest): Promise<SkillImportResponse> =>
  api.post('/skills/import', payload);

export const getCodexDefaults = (): Promise<CodexDefaults> =>
  api.get('/settings/codex-defaults');
export const getDeploymentVersion = (): Promise<DeploymentVersionResponse> =>
  api.get('/settings/deployment-version');
export const getFrontendBuildVersion = (): Promise<DeploymentVersionResponse> =>
  fetch('/build-info.json', { headers: { Accept: 'application/json' } })
    .then((response) => response.ok
      ? response.json() as Promise<DeploymentVersionResponse>
      : { short_commit: null, committed_at: null })
    .catch(() => ({ short_commit: null, committed_at: null }));

export const getSkillRegistries = (): Promise<SkillRegistryListResponse> =>
  api.get('/skill-registries');
export const getSkillRegistryStatus = (registryId: string): Promise<SkillRegistryStatus> =>
  api.get(`/skill-registries/${registryId}/status`);
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

export const getAdminUsers = (): Promise<AdminUserListResponse> => api.get('/admin/users');
export const updateAdminUser = (
  userId: string,
  payload: AdminUserUpdateRequest,
): Promise<AdminUserItem> => api.patch(`/admin/users/${userId}`, payload);
export const resetUserPassword = (
  userId: string,
  payload: AdminPasswordResetRequest,
): Promise<void> => api.put(`/admin/users/${userId}/password`, payload);
export const getEnvAccess = (environmentId: string): Promise<EnvAccessListResponse> =>
  api.get(`/admin/environments/${environmentId}/access`);
export const grantEnvAccess = (
  environmentId: string,
  payload: EnvAccessRequest,
): Promise<EnvAccessItem> => api.put(`/admin/environments/${environmentId}/access`, payload);
export const revokeEnvAccess = (environmentId: string, userId: string): Promise<void> =>
  api.delete(`/admin/environments/${environmentId}/access/${userId}`);
