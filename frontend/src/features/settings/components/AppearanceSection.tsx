import { useState } from 'react';
import { Button, FormField, SectionCard, SectionHeader, NativeSelect, Switch } from '@design-system';
import { useT } from '@/shared/i18n';
import type { WebUiSettingsDocument } from '@features/settings/types';

export interface AppearanceSectionProps {
  savedAppearance: WebUiSettingsDocument['general']['appearance'];
  onSave: (appearance: WebUiSettingsDocument['general']['appearance']) => void;
  onReset: () => void;
}

export function AppearanceSection({ savedAppearance, onSave, onReset }: AppearanceSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState(savedAppearance);
  const hasChanges = draft.theme !== savedAppearance.theme
    || draft.motionEnabled !== savedAppearance.motionEnabled;

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.appearance.title')}
          description={t('pages.settings.appearance.description')}
        />
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <FormField label={t('pages.settings.appearance.themeLabel')}>
          <NativeSelect
            aria-label={t('pages.settings.appearance.themeLabel')}
            value={draft.theme}
            onChange={(event) =>
              setDraft({ ...draft, theme: event.target.value as 'light' | 'dark' | 'system' })
            }
          >
            <option value="light">{t('pages.settings.appearance.light')}</option>
            <option value="dark">{t('pages.settings.appearance.dark')}</option>
            <option value="system">{t('pages.settings.appearance.system')}</option>
          </NativeSelect>
        </FormField>
        <FormField label={t('pages.settings.appearance.motionLabel')}>
          <div className="flex min-h-10 items-center justify-between gap-4 rounded-lg border border-[var(--osci-color-border-subtle)] px-3">
            <span className="text-sm text-[var(--osci-color-text-secondary)]">
              {t('pages.settings.appearance.motionDescription')}
            </span>
            <Switch
              aria-label={t('pages.settings.appearance.motionLabel')}
              checked={draft.motionEnabled}
              onCheckedChange={(motionEnabled) => setDraft({ ...draft, motionEnabled })}
            />
          </div>
        </FormField>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
        <p>{t('pages.settings.appearance.previewHint')}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={onReset}>
            {t('common.reset')}
          </Button>
          <Button onClick={() => onSave(draft)} disabled={!hasChanges}>
            {t('common.saveChanges')}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
