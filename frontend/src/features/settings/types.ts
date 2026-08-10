import type { SkillMode, ThemePreference } from '@design-system';
import type {
  AdminUserResponse as TransportAdminUserResponse,
  CodexDefaultsResponse,
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

export type { SkillMode, ThemePreference } from '@design-system';

export type DefaultRoute = 'today' | 'projects' | 'terminal' | 'tasks' | 'workspaces' | 'environments';

export type ExecutionEngineId = 'claude-code' | 'agent-sdk' | 'codex-app-server';
export type CodexConfigSource = 'host_default' | 'custom';
export type TaskConfigurationMode = 'raw_prompt' | 'structured_research' | 'reproduce_baseline' | 'discover_ideas' | 'validate_ideas';

export interface ResearchAgentProfileSettings {
  profileId: string;
  label: string;
  systemPrompt: string;
  skills: string[];
  skillModes: Record<string, SkillMode>;
  skillsPrompt: string;
  settingsJson: string;
  apiBaseUrl: string;
  apiKey: string;
  defaultOpusModel: string;
  defaultSonnetModel: string;
  defaultHaikuModel: string;
  envOverrides: string;
  codexBaseUrl: string;
  codexApiKey: string;
  codexModel: string;
  codexAppServerCommand: string;
  codexApprovalPolicy: string;
  codexConfigToml: string;
  codexAuthJson: string;
  codexConfigTomlSource: CodexConfigSource;
  codexAuthJsonSource: CodexConfigSource;
}

export interface TaskConfigurationPreset {
  configId: string;
  label: string;
  mode: TaskConfigurationMode;
}

export interface EnvironmentTaskDefaults {
  titleTemplate: string;
  taskInputTemplate: string;
  researchAgentProfileId: string;
  taskConfigurationId: string;
}

export interface DefaultProjectSelectionState {
  lastEnvironmentId: string | null;
  lastWorkspaceId: string | null;
}

export interface DefaultProjectSettings {
  defaultEnvironmentId: string | null;
  defaultWorkspaceId: string | null;
  selection: DefaultProjectSelectionState;
  environmentDefaults: Record<string, EnvironmentTaskDefaults>;
}

export interface AppearanceSettings {
  theme: ThemePreference;
  motionEnabled: boolean;
}

export interface TaskConfigurationSettings {
  defaultExecutionEngineId: ExecutionEngineId;
  researchAgentProfiles: ResearchAgentProfileSettings[];
  taskConfigurations: TaskConfigurationPreset[];
  defaultResearchAgentProfileId: string;
  defaultTaskConfigurationId: string;
}

export type LlmProviderFormat = 'anthropic' | 'openai-chat' | 'openai-responses';

export interface LlmProvider {
  id: string;
  name: string;
  format: LlmProviderFormat;
  baseUrl: string;
  apiKey: string;
  opusModel?: string;
  sonnetModel?: string;
  haikuModel?: string;
  defaultModel?: string;
}

export interface WebUiSettingsDocument {
  version: 5;
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
  taskConfiguration: TaskConfigurationSettings;
  projectDefaults: Record<string, DefaultProjectSettings>;
  llmProviders: LlmProvider[];
}

export type SettingsRecoveryReason = 'invalid_document' | 'unsupported_version';

export type CodexDefaults = CodexDefaultsResponse;
export type SkillItem = SkillItemResponse & { description: string | null; dependencies: string[]; inject_mode: 'auto' | 'prompt_only' | 'disabled'; package?: string };
export type SkillListResponse = { items: SkillItem[] };
export type SkillDetail = SkillDetailResponse & { description: string | null; dependencies: string[]; skill_md: string | null; package?: string };
export type SkillImportResponse = TransportSkillImportResponse;
export type SkillImportInput = {
  source: 'git' | 'local';
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

export function toSkillImportRequest(value: SkillImportInput): SkillImportRequest {
  return {
    source: value.source,
    url: value.url,
    local_path: value.localPath,
    skill_id: value.skillId,
  };
}

export function adaptSkill(value: SkillItemResponse): SkillItem {
  const injectMode = value.inject_mode === 'prompt_only' || value.inject_mode === 'disabled' ? value.inject_mode : 'auto';
  return {
    skill_id: value.skill_id,
    label: value.label,
    description: value.description ?? null,
    inject_mode: injectMode,
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
