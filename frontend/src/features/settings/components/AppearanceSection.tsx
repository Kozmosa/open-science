import { useState } from 'react';
import { Button, FormField, SectionCard, SectionHeader, Select } from '@design-system/primitives';
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
  const hasChanges = draft.fontFamily !== savedAppearance.fontFamily;

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
        <FormField label={t('pages.settings.appearance.fontFamilyLabel')}>
          <Select
            aria-label={t('pages.settings.appearance.fontFamilyLabel')}
            value={draft.fontFamily}
            onChange={(event) =>
              setDraft({ fontFamily: event.target.value as 'sans-serif' | 'serif' })
            }
          >
            <option value="sans-serif">{t('pages.settings.appearance.sansSerif')}</option>
            <option value="serif">{t('pages.settings.appearance.serif')}</option>
          </Select>
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
