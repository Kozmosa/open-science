import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, PageHeader, PageShell, SectionStack } from '@design-system';
import { EnvironmentSelectorPanel, useEnvironmentSelection } from '@features/environments';
import { getEnvironments } from '@features/environments/api/queries';
import { getSkills } from '../api';
import { useEnvironmentSelectionPreferences, useSettings } from '../contexts/SettingsProvider';
import { useT } from '@/shared/i18n';
import { useAuth } from '@features/auth';
import { UsersTab } from './settings/UsersTab';
import { EnvAccessTab } from './settings/EnvAccessTab';
import { CollaboratorsTab } from './settings/CollaboratorsTab';
import MonitoringTab from './settings/MonitoringTab';
import { AccountSection } from '../components/AccountSection';
import { AppearanceSection } from '../components/AppearanceSection';
import { ChangePasswordModal } from '../components/ChangePasswordModal';
import { DeploymentVersionSection } from '../components/DeploymentVersionSection';
import { GeneralPreferencesSection } from '../components/GeneralPreferencesSection';
import { ProjectDefaultsSection } from '../components/ProjectDefaultsSection';
import { SearchBackendSection } from '../components/SearchBackendSection';
import { SkillRepositorySection } from '../components/SkillRepositorySection';
import { queryKeys } from '@/shared/api/queryKeys';

function SettingsPage() {
  const t = useT();
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState<'general' | 'monitoring' | 'users' | 'envAccess' | 'collaborators'>('general');
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const environmentsQuery = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: getEnvironments,
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
    saveProjectDefaultEnvironment,
    saveAppearanceSettings,
    resetAppearanceSettings,
  } = useSettings();
  const environmentSelectionPreferences = useEnvironmentSelectionPreferences();
  const environmentSelection = useEnvironmentSelection(undefined, environmentSelectionPreferences);
  const defaultProjectId = environmentSelection.projectId;
  const defaultProjectSettings = defaultProjectId
    ? settings.projectDefaults[defaultProjectId] ?? settings.projectDefaults.default
    : settings.projectDefaults.default;

  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const availableSkills = useMemo(
    () => skillsQuery.data?.items ?? [],
    [skillsQuery.data]
  );
  const environmentsError =
    environmentsQuery.error instanceof Error ? environmentsQuery.error.message : null;

  const tabs = [
    { key: 'general' as const, label: t('pages.settings.tabs.general') },
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

          <SkillRepositorySection availableSkills={availableSkills} />
          <AccountSection onPasswordClick={() => setShowPasswordModal(true)} />
          <DeploymentVersionSection />
          <ChangePasswordModal open={showPasswordModal} onClose={() => setShowPasswordModal(false)} />
          <SearchBackendSection />

          <ProjectDefaultsSection
            key={`project-default:${defaultProjectId ?? 'unresolved'}:${defaultProjectSettings?.defaultEnvironmentId ?? 'none'}`}
            environments={environments}
            savedDefaultEnvironmentId={defaultProjectSettings?.defaultEnvironmentId ?? null}
            isLoading={environmentsQuery.isLoading}
            loadError={environmentsError}
            saveProjectDefaultEnvironment={(environmentId) => {
              if (defaultProjectId) saveProjectDefaultEnvironment(defaultProjectId, environmentId);
            }}
          />
        </SectionStack>
        )}

        {activeTab === 'monitoring' && <MonitoringTab />}
        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'envAccess' && <EnvAccessTab />}
        {activeTab === 'collaborators' && <CollaboratorsTab />}
      </div>
    </PageShell>
  );
}

export default SettingsPage;
