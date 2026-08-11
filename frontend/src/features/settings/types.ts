import type { ThemePreference } from '@design-system';
import type {
  AdminUserResponse as TransportAdminUserResponse,
  DeploymentVersionResponse as TransportDeploymentVersionResponse,
  EnvironmentAccessResponse,
  MonitoringServiceItem as TransportMonitoringServiceItem,
  SearchBackendItem as TransportSearchBackendItem,
  SkillDetailResponse,
  SkillImportRequest,
  SkillImportResponse as TransportSkillImportResponse,
  SkillItemResponse,
  SkillRegistryInstallResponse as TransportSkillRegistryInstallResponse,
  SkillRegistryItemResponse,
  SkillRegistryStatusResponse,
  SkillRegistryUpdateResponse as TransportSkillRegistryUpdateResponse,
} from '@/generated/transport';

export type { ThemePreference } from '@design-system';

export type DefaultRoute = 'today' | 'projects' | 'terminal' | 'tasks' | 'workspaces' | 'environments';

export interface DefaultProjectSelectionState {
  lastEnvironmentId: string | null;
}

export interface DefaultProjectSettings {
  defaultEnvironmentId: string | null;
  selection: DefaultProjectSelectionState;
}

export interface AppearanceSettings {
  theme: ThemePreference;
  motionEnabled: boolean;
}

export interface WebUiSettingsDocument {
  version: 6;
  general: {
    defaultRoute: DefaultRoute;
    terminal: {
      fontSize: number;
    };
    editor: {
      fontSize: number;
      fontFamily: string;
    };
    appearance: AppearanceSettings;
  };
  projectDefaults: Record<string, DefaultProjectSettings>;
}

export type SettingsRecoveryReason = 'invalid_document' | 'unsupported_version';

export type SkillInjectMode = NonNullable<SkillItemResponse['inject_mode']>;
export type SkillItem = SkillItemResponse & { description: string | null; dependencies: string[]; inject_mode: SkillInjectMode; package?: string };
export type SkillListResponse = { items: SkillItem[] };
export type SkillDetail = SkillDetailResponse & { description: string | null; dependencies: string[]; skill_md: string | null; package?: string };
export type SkillImportResponse = TransportSkillImportResponse;
export type SkillImportSource = SkillImportRequest['source'];
export type SkillImportInput = {
  source: SkillImportSource;
  url: string | null;
  localPath: string | null;
  skillId: string | null;
};
export type SkillRegistryItem = SkillRegistryItemResponse & { git_url: string; last_sync_at: string | null };
export type SkillRegistryListResponse = { items: SkillRegistryItem[] };
export type SkillRegistryStatus = SkillRegistryStatusResponse & { last_sync_at: string | null; remote_commit: string | null; local_commit: string | null };
export type SkillRegistryInstallResponse = TransportSkillRegistryInstallResponse;
export type SkillRegistryUpdateResponse = TransportSkillRegistryUpdateResponse;
export type AdminUserItem = TransportAdminUserResponse;
export type AdminUserResponse = TransportAdminUserResponse;
export type AdminUserListResponse = { items: AdminUserItem[] };
export type EnvAccessItem = EnvironmentAccessResponse;
export type EnvAccessListResponse = { items: EnvAccessItem[] };
export type SearchBackendItem = TransportSearchBackendItem;
export type SearchSettingsResponse = { active_backend: string; available_backends: SearchBackendItem[]; auto_start_mcp_servers: string[] };
export type DeploymentVersionResponse = TransportDeploymentVersionResponse;
export type MonitoringServiceItem = TransportMonitoringServiceItem;
export type MonitoringSettingsResponse = { services: MonitoringServiceItem[] };

export function parseSkillImportSource(value: string): SkillImportSource | null {
  return value === 'git' || value === 'local' ? value : null;
}

export function toSkillImportRequest(value: SkillImportInput): SkillImportRequest {
  return {
    source: value.source,
    url: value.url,
    local_path: value.localPath,
    skill_id: value.skillId,
  };
}

export function adaptSkill(value: SkillItemResponse): SkillItem {
  return {
    skill_id: value.skill_id,
    label: value.label,
    description: value.description ?? null,
    inject_mode: value.inject_mode ?? 'auto',
    dependencies: value.dependencies ?? [],
    package: value.package ?? undefined,
  };
}

export function adaptSkillList(value: { items: SkillItemResponse[] }): SkillListResponse {
  return { items: value.items.map(adaptSkill) };
}

export function adaptSkillDetail(value: SkillDetailResponse): SkillDetail {
  return {
    ...value,
    description: value.description ?? null,
    dependencies: value.dependencies ?? [],
    skill_md: value.skill_md ?? null,
    package: value.package ?? undefined,
  };
}

export function adaptSkillRegistries(value: { items: SkillRegistryItemResponse[] }): SkillRegistryListResponse {
  return {
    items: value.items.map((item) => ({
      ...item,
      installed: item.installed ?? false,
      installed_count: item.installed_count ?? 0,
      has_update: item.has_update ?? false,
      is_dirty: item.is_dirty ?? false,
      last_sync_at: item.last_sync_at ?? null,
    })),
  };
}

export function adaptSkillRegistryStatus(value: SkillRegistryStatusResponse): SkillRegistryStatus {
  return { ...value, last_sync_at: value.last_sync_at ?? null, remote_commit: value.remote_commit ?? null, local_commit: value.local_commit ?? null };
}
