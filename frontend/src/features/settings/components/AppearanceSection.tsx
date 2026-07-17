import { useState } from 'react';
import { Button, FormField, SectionCard, SectionHeader, NativeSelect } from '@design-system';
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
  const hasChanges = draft.theme !== savedAppearance.theme;

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
              setDraft({ theme: event.target.value as 'light' | 'dark' | 'system' })
            }
          >
            <option value="light">{t('pages.settings.appearance.light')}</option>
            <option value="dark">{t('pages.settings.appearance.dark')}</option>
            <option value="system">{t('pages.settings.appearance.system')}</option>
          </NativeSelect>
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
