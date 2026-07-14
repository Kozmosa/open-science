import { useState } from 'react';
import { Button, FormField, SectionCard, SectionHeader, NativeSelect } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { EnvironmentTaskDefaults, TaskConfigurationSettings } from '@features/settings';
import type { EnvironmentRecord } from '@/shared/types';
import { EnvironmentDefaultsCard } from './EnvironmentDefaultsCard';

export interface ProjectDefaultsSectionProps {
  environments: EnvironmentRecord[];
  taskConfiguration: TaskConfigurationSettings;
  savedDefaultEnvironmentId: string | null;
  isLoading: boolean;
  loadError: string | null;
  getProjectEnvironmentDefaults: (environmentId: string | null) => EnvironmentTaskDefaults;
  saveProjectDefaultEnvironment: (environmentId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (environmentId: string) => void;
}

export function ProjectDefaultsSection({
  environments,
  taskConfiguration,
  savedDefaultEnvironmentId,
  isLoading,
  loadError,
  getProjectEnvironmentDefaults,
  saveProjectDefaultEnvironment,
  saveProjectEnvironmentDefaults,
  resetProjectEnvironmentDefaults,
}: ProjectDefaultsSectionProps) {
  const t = useT();
  const [defaultEnvironmentDraft, setDefaultEnvironmentDraft] = useState<string>(
    savedDefaultEnvironmentId ?? ''
  );
  const persistedProjectDefaultEnvironmentId = savedDefaultEnvironmentId ?? '';
  const hasProjectDefaultChanges = defaultEnvironmentDraft !== persistedProjectDefaultEnvironmentId;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.project.title')}
          description={t('pages.settings.project.description')}
        />
      }
    >

      <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
        <FormField label={t('pages.settings.project.defaultEnvironmentLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.project.defaultEnvironmentLabel')}
            value={defaultEnvironmentDraft}
            onChange={(event) => setDefaultEnvironmentDraft(event.target.value)}
            disabled={environments.length === 0}
          >
            <option value="">{t('pages.settings.project.defaultEnvironmentEmpty')}</option>
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </NativeSelect>
        </FormField>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.settings.project.defaultEnvironmentHelp')}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => saveProjectDefaultEnvironment(null)}>
              {t('common.reset')}
            </Button>
            <Button
              onClick={() => saveProjectDefaultEnvironment(defaultEnvironmentDraft || null)}
              disabled={!hasProjectDefaultChanges}
            >
              {t('common.saveChanges')}
            </Button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('common.loading')}
        </p>
      ) : null}
      {loadError ? <p className="text-sm text-[#ff3b30]">{loadError}</p> : null}
      {environments.length === 0 && !isLoading ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('pages.settings.project.noEnvironments')}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {environments.map((environment) => {
          const savedDefaults = getProjectEnvironmentDefaults(environment.id);
          return (
            <EnvironmentDefaultsCard
              key={`${environment.id}:${savedDefaults.titleTemplate}:${savedDefaults.taskInputTemplate}:${savedDefaults.researchAgentProfileId}:${savedDefaults.taskConfigurationId}`}
              environment={environment}
              savedDefaults={savedDefaults}
              taskConfiguration={taskConfiguration}
              onSave={(defaults) => saveProjectEnvironmentDefaults(environment.id, defaults)}
              onReset={() => resetProjectEnvironmentDefaults(environment.id)}
            />
          );
        })}
      </div>
    </SectionCard>
  );
}

