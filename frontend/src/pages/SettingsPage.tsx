import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, FormField, PageHeader, SectionCard, SectionHeader, Select } from '@design-system/primitives';
import { PageShell, SectionStack } from '@design-system/layout';
import { EnvironmentSelectorPanel, useEnvironmentSelection } from '@/components/environment';
import { getEnvironments, getSkills, getWorkspaces } from '@/shared/api';
import { useSettings } from '@features/settings';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';
import { UsersTab } from './settings/UsersTab';
import { EnvAccessTab } from './settings/EnvAccessTab';
import { CollaboratorsTab } from './settings/CollaboratorsTab';
import { LlmProvidersTab } from './settings/LlmProvidersTab';
import MonitoringTab from './settings/MonitoringTab';
import { AccountSection } from '@features/settings/components/AccountSection.tsx';
import { AppearanceSection } from '@features/settings/components/AppearanceSection.tsx';
import { ChangePasswordModal } from '@features/settings/components/ChangePasswordModal.tsx';
import { DeploymentVersionSection } from '@features/settings/components/DeploymentVersionSection.tsx';
import { GeneralPreferencesSection } from '@features/settings/components/GeneralPreferencesSection.tsx';
import { ProjectDefaultsSection } from '@features/settings/components/ProjectDefaultsSection.tsx';
import { SearchBackendSection } from '@features/settings/components/SearchBackendSection.tsx';
import { SkillRepositorySection } from '@features/settings/components/SkillRepositorySection.tsx';
import { TaskConfigurationSection } from '@features/settings/components/TaskConfigurationSection.tsx';
import { queryKeys } from '@/shared/api/queryKeys';

function SettingsPage() {
  const t = useT();
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState<'general' | 'llmProviders' | 'monitoring' | 'users' | 'envAccess' | 'collaborators'>('general');
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const environmentsQuery = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: getEnvironments,
  });
  const workspacesQuery = useQuery({
    queryKey: queryKeys.workspaces.all,
    queryFn: getWorkspaces,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.all,
    queryFn: getSkills,
  });
  const {
    settings,
    recoveryReason,
    saveGeneralPreferences,
    resetGeneralPreferences,
    saveTaskConfigurationSettings,
    resetTaskConfigurationSettings,
    saveProjectDefaultEnvironment,
    saveProjectDefaultWorkspace,
    saveProjectEnvironmentDefaults,
    resetProjectEnvironmentDefaults,
    getProjectEnvironmentDefaults,
    saveAppearanceSettings,
    resetAppearanceSettings,
  } = useSettings();
  const environmentSelection = useEnvironmentSelection();

  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const workspaces = useMemo(
    () => workspacesQuery.data?.items ?? [],
    [workspacesQuery.data]
  );
  const availableSkills = useMemo(
    () => skillsQuery.data?.items ?? [],
    [skillsQuery.data]
  );
  const environmentsError =
    environmentsQuery.error instanceof Error ? environmentsQuery.error.message : null;

  const tabs = [
    { key: 'general' as const, label: t('pages.settings.tabs.general') },
    { key: 'llmProviders' as const, label: t('pages.settings.tabs.llmProviders') },
    { key: 'monitoring' as const, label: t('pages.settings.tabs.monitoring') },
    ...(currentUser?.role === 'admin' ? [
      { key: 'users' as const, label: t('pages.settings.tabs.users') },
      { key: 'envAccess' as const, label: t('pages.settings.tabs.envAccess') },
      { key: 'collaborators' as const, label: t('pages.settings.tabs.collaborators') },
    ] : []),
  ];

  return (
    <PageShell>
      <div className="space-y-6 p-3">
        <PageHeader
          eyebrow={t('pages.settings.eyebrow')}
          title={t('pages.settings.title')}
          description={t('pages.settings.description')}
        />

        <div className="flex gap-1 border-b border-[var(--border)] pb-0">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg border border-b-0 -mb-px transition-colors ${
                activeTab === tab.key
                  ? 'bg-[var(--surface)] border-[var(--border)] text-[var(--text)]'
                  : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--bg-secondary)]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'general' && (
          <SectionStack>
          {recoveryReason !== null ? <Alert variant="warning">{t('pages.settings.recoveryNotice')}</Alert> : null}

          <GeneralPreferencesSection
            key={`general:${settings.general.defaultRoute}:${settings.general.terminal.fontSize}`}
            savedGeneral={settings.general}
            onSave={saveGeneralPreferences}
            onReset={resetGeneralPreferences}
          />

          <AppearanceSection
            savedAppearance={settings.general.appearance}
            onSave={saveAppearanceSettings}
            onReset={resetAppearanceSettings}
          />

          <EnvironmentSelectorPanel {...environmentSelection} />

          <SectionCard
            collapsible
            header={
              <SectionHeader
                title={t('pages.settings.defaultWorkspace.title')}
                description={t('pages.settings.defaultWorkspace.description')}
              />
            }
          >
            <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
              <FormField label={t('pages.settings.defaultWorkspace.label')}>
                <Select
                  aria-label={t('pages.settings.defaultWorkspace.label')}
                  value={settings.projectDefaults.default?.defaultWorkspaceId ?? ''}
                  onChange={(event) =>
                    saveProjectDefaultWorkspace('default', event.target.value || null)
                  }
                  disabled={workspaces.length === 0}
                >
                  <option value="">{t('pages.settings.defaultWorkspace.noDefault')}</option>
                  {workspaces.map((workspace) => (
                    <option key={workspace.workspace_id} value={workspace.workspace_id}>
                      {workspace.label}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </SectionCard>

          <TaskConfigurationSection
            taskConfiguration={settings.taskConfiguration}
            availableSkills={availableSkills}
            onSaveTaskConfigurationSettings={saveTaskConfigurationSettings}
            onResetTaskConfigurationSettings={resetTaskConfigurationSettings}
          />

          <SkillRepositorySection availableSkills={availableSkills} />
          <AccountSection onPasswordClick={() => setShowPasswordModal(true)} />
          <DeploymentVersionSection />
          <ChangePasswordModal open={showPasswordModal} onClose={() => setShowPasswordModal(false)} />
          <SearchBackendSection />

          <ProjectDefaultsSection
            key={`project-default:${settings.projectDefaults.default?.defaultEnvironmentId ?? 'none'}`}
            environments={environments}
            taskConfiguration={settings.taskConfiguration}
            savedDefaultEnvironmentId={settings.projectDefaults.default?.defaultEnvironmentId ?? null}
            isLoading={environmentsQuery.isLoading}
            loadError={environmentsError}
            getProjectEnvironmentDefaults={(environmentId) =>
              getProjectEnvironmentDefaults('default', environmentId)
            }
            saveProjectDefaultEnvironment={(environmentId) =>
              saveProjectDefaultEnvironment('default', environmentId)
            }
            saveProjectEnvironmentDefaults={(environmentId, defaults) =>
              saveProjectEnvironmentDefaults('default', environmentId, defaults)
            }
            resetProjectEnvironmentDefaults={(environmentId) =>
              resetProjectEnvironmentDefaults('default', environmentId)
            }
          />
        </SectionStack>
        )}

        {activeTab === 'llmProviders' && <LlmProvidersTab />}
        {activeTab === 'monitoring' && <MonitoringTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'envAccess' && <EnvAccessTab />}
        {activeTab === 'collaborators' && <CollaboratorsTab />}
      </div>
    </PageShell>
  );
}

export default SettingsPage;
