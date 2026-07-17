import { useState } from 'react';
import { Button, FormField, Input, SectionCard, SectionHeader, NativeSelect, Textarea } from '@design-system';
import { useT } from '@/shared/i18n';
import type { EnvironmentTaskDefaults, TaskConfigurationSettings } from '@features/settings';
import type { EnvironmentRecord } from '@/shared/types';
import { hasEnvironmentDefaultChanges } from './settingsHelpers';

export interface EnvironmentDefaultsCardProps {
  environment: EnvironmentRecord;
  savedDefaults: EnvironmentTaskDefaults;
  onSave: (defaults: EnvironmentTaskDefaults) => void;
  onReset: () => void;
}

export function EnvironmentDefaultsCard({
  environment,
  savedDefaults,
  taskConfiguration,
  onSave,
  onReset,
}: EnvironmentDefaultsCardProps & { taskConfiguration: TaskConfigurationSettings }) {
  const t = useT();
  const [draft, setDraft] = useState<EnvironmentTaskDefaults>(savedDefaults);
  const hasChanges = hasEnvironmentDefaultChanges(draft, savedDefaults);

  return (
    <SectionCard
      collapsible
      defaultExpanded={false}
      header={
        <SectionHeader
          title={`${environment.alias} · ${environment.display_name}`}
          description={t('pages.settings.project.environmentCardDescription')}
          size="sm"
        />
      }
      className="space-y-4 p-5"
    >

      <FormField label={t('pages.settings.project.titleTemplateLabel')}>
        <Input
          aria-label={`${environment.alias} ${t('pages.settings.project.titleTemplateLabel')}`}
          value={draft.titleTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              titleTemplate: event.target.value,
            }))
          }
          placeholder={t('pages.settings.project.titleTemplatePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.settings.project.taskInputTemplateLabel')}>
        <Textarea
          aria-label={`${environment.alias} ${t('pages.settings.project.taskInputTemplateLabel')}`}
          value={draft.taskInputTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskInputTemplate: event.target.value,
            }))
          }
          className="min-h-32"
          placeholder={t('pages.settings.project.taskInputTemplatePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.settings.project.researchAgentDefaultLabel')}>
        <NativeSelect
          aria-label={`${environment.alias} ${t('pages.settings.project.researchAgentDefaultLabel')}`}
          value={draft.researchAgentProfileId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              researchAgentProfileId: event.target.value,
            }))
          }
        >
          {taskConfiguration.researchAgentProfiles.map((profile) => (
            <option key={profile.profileId} value={profile.profileId}>
              {profile.label}
            </option>
          ))}
        </NativeSelect>
      </FormField>

      <FormField label={t('pages.settings.project.taskConfigurationDefaultLabel')}>
        <NativeSelect
          aria-label={`${environment.alias} ${t('pages.settings.project.taskConfigurationDefaultLabel')}`}
          value={draft.taskConfigurationId}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskConfigurationId: event.target.value,
            }))
          }
        >
          {taskConfiguration.taskConfigurations.map((config) => (
            <option key={config.configId} value={config.configId}>
              {config.label}
            </option>
          ))}
        </NativeSelect>
      </FormField>

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="secondary" onClick={onReset}>
          {t('common.reset')}
        </Button>
        <Button onClick={() => onSave(draft)} disabled={!hasChanges}>
          {t('common.saveChanges')}
        </Button>
      </div>
    </SectionCard>
  );
}

